/** Internal optional pool resources. Borrowed transport security belongs to the caller. */
import { AsyncLocalStorage } from 'node:async_hooks';
import { constants } from 'node:fs';
import { open, readFile, stat } from 'node:fs/promises';
import { isAbsolute } from 'node:path';
import { z } from 'zod';
import { DeadlineExceeded, InvalidRequest, ProviderUnavailable, UnsupportedCapability } from './errors.js';
import { valid_native_json } from './shared.js';

const duration = (maximum: number) => z.number().finite().positive().max(maximum);
const path = z.string().refine(value => isAbsolute(value) && !/[\0\r\n]/.test(value));
const ConfigSchema = z.custom<unknown>(valid_native_json).pipe(z.strictObject({
  host: z.string().regex(/^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$/),
  port: z.number().int().min(1).max(65535).default(5432),
  dbname: z.string().regex(/^[A-Za-z0-9_.@-]+$/), user: z.string().regex(/^[A-Za-z0-9_.@-]+$/),
  sslrootcert: path, passfile: path,
  max_size: z.number().int().min(1).max(2).default(2),
  max_waiting: z.number().int().min(0).max(16).default(4),
  startup_timeout: duration(30).default(5), acquire_timeout: duration(30).default(2),
  close_timeout: duration(10).default(2), release_timeout: duration(5).default(1),
})).refine(value => value.release_timeout <= value.close_timeout).transform(value => Object.freeze(value));
export type PoolConfig = z.infer<typeof ConfigSchema>;
export function parse_pool_config(input: unknown): PoolConfig {
  try { return ConfigSchema.parse(input); } catch { throw new InvalidRequest(); }
}
export interface PgClient {
  query(config: { text: string; values?: readonly unknown[]; rowMode: 'array' }): Promise<{ rows: unknown[][] }>;
  getTransactionStatus(): string | null;
  release(destroy?: boolean): void;
}
export interface PgPool { connect(): Promise<PgClient>; end(): Promise<void>; }
export type PoolFactory = (config: PoolConfig) => PgPool | Promise<PgPool>;
export type LeaseOptions = Readonly<{ deadline: number; signal?: AbortSignal }>;
export const now = (): number => performance.now() / 1000;
export const abort_error = (): DOMException => new DOMException('Operation aborted.', 'AbortError');
export function check_options(options: LeaseOptions): void {
  if (!options || typeof options.deadline !== 'number' || !Number.isFinite(options.deadline)
      || (options.signal !== undefined && !(options.signal instanceof AbortSignal))) throw new InvalidRequest();
  if (options.deadline <= now()) throw new DeadlineExceeded();
  if (options.signal?.aborted) throw abort_error();
}

/** Race without abandoning rejection handlers; callers dispose any late resource. */
export async function bounded<T>(operation: Promise<T>, options: LeaseOptions,
                                 stop?: (error: Error) => void): Promise<T> {
  void operation.catch(() => {});
  const safelyStop = (error: Error): void => { try { stop?.(error); } catch {} };
  try { check_options(options); } catch (error) { safelyStop(error as Error); throw error; }
  let timer: ReturnType<typeof setTimeout> | undefined;
  let listener: (() => void) | undefined;
  const stopped = new Promise<never>((_, reject) => {
    const fail = (error: Error): void => { reject(error); safelyStop(error); };
    timer = setTimeout(() => fail(new DeadlineExceeded()), Math.min(2_147_483_647, Math.max(1, (options.deadline - now()) * 1000)));
    if (options.signal) {
      listener = () => fail(abort_error());
      options.signal.addEventListener('abort', listener, { once: true });
    }
  });
  try {
    const result = await Promise.race([operation, stopped]);
    if (now() >= options.deadline) { const error = new DeadlineExceeded(); safelyStop(error); throw error; }
    if (options.signal?.aborted) { const error = abort_error(); safelyStop(error); throw error; }
    return result;
  } finally {
    clearTimeout(timer);
    if (listener) options.signal?.removeEventListener('abort', listener);
  }
}

async function check_files(config: PoolConfig): Promise<void> {
  if (Object.entries(process.env).some(([key, value]) => key.startsWith('PG') && value)) throw new InvalidRequest();
  try {
    const ca = await stat(config.sslrootcert);
    const file = await open(config.passfile, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const info = await file.stat();
      if (!ca.isFile() || ca.size > 1_048_576 || !info.isFile() || info.size > 65_536
          || info.uid !== process.getuid?.() || (info.mode & 0o077)) throw new InvalidRequest();
    } finally { await file.close(); }
  } catch { throw new InvalidRequest(); }
}
function password_for(contents: string, config: PoolConfig): string {
  const entries = contents.split(/\r?\n/).filter(line => line && !line.startsWith('#'));
  if (entries.length !== 1) throw new InvalidRequest();
  const fields: string[] = [''];
  let escaped = false;
  for (const char of entries[0]) {
    if (escaped) { fields[fields.length - 1] += char; escaped = false; }
    else if (char === '\\') escaped = true;
    else if (char === ':') fields.push('');
    else fields[fields.length - 1] += char;
  }
  if (escaped || fields.length !== 5 || fields.some(field => /[\r\n\0]/.test(field))
      || fields.slice(0, 4).some(field => field === '*') || !fields[4]
      || fields.slice(0, 4).join('\0') !== [config.host, String(config.port), config.dbname, config.user].join('\0')) throw new InvalidRequest();
  return fields[4];
}
async function default_factory(config: PoolConfig): Promise<PgPool> {
  const file = await open(config.passfile, constants.O_RDONLY | constants.O_NOFOLLOW);
  let password: string;
  try {
    const info = await file.stat();
    if (!info.isFile() || info.uid !== process.getuid?.() || (info.mode & 0o077) || info.size > 65_536) throw new InvalidRequest();
    password = password_for(await file.readFile('utf8'), config);
  } finally { await file.close(); }
  const ca = await readFile(config.sslrootcert, 'utf8');
  const name = 'pg';
  let driver: { Pool: new (options: object) => PgPool };
  try { driver = await import(name) as typeof driver; } catch { throw new UnsupportedCapability(); }
  const pool = new driver.Pool({ host: config.host, port: config.port, database: config.dbname,
    user: config.user, password, ssl: { ca, rejectUnauthorized: true, servername: config.host },
    max: config.max_size, min: 1, connectionTimeoutMillis: Math.ceil(config.acquire_timeout * 1000),
    idleTimeoutMillis: 10_000, application_name: 'cragkit-resource' });
  // An idle-client error must not crash the host or print raw provider details.
  const events = pool as PgPool & { on?: (event: string, listener: () => void) => void };
  events.on?.('error', () => {});
  return pool;
}

type Work = { controller: AbortController; done: Promise<void>; finish: () => void; client?: PgClient; released: boolean };
const context = new AsyncLocalStorage<ReadonlySet<PoolResource>>();
export class PoolResource {
  readonly config: PoolConfig;
  private pool?: PgPool;
  private readonly owned: boolean;
  private readonly factory: PoolFactory;
  private state: 'new' | 'open' | 'closing' | 'closed';
  private startup?: Promise<void>;
  private startupController = new AbortController();
  private closing?: Promise<void>;
  private driverEnded = new WeakMap<PgPool, Promise<void>>();
  private readonly work = new Set<Work>();
  private readonly connecting = new Set<Promise<unknown>>();
  constructor(config: PoolConfig, options: { pool?: PgPool; factory?: PoolFactory } = {}) {
    this.config = parse_pool_config(config);
    if (options.pool && options.factory) throw new InvalidRequest();
    this.pool = options.pool; this.owned = !options.pool;
    this.factory = options.factory ?? default_factory;
    this.state = this.owned ? 'new' : 'open';
  }
  private end_driver(pool = this.pool): Promise<void> {
    if (!this.owned || !pool) return Promise.resolve();
    let ending = this.driverEnded.get(pool);
    if (!ending) { ending = Promise.resolve().then(() => pool.end()); this.driverEnded.set(pool, ending); }
    return ending;
  }
  async open(): Promise<void> {
    if (this.state === 'open') return;
    if (this.state !== 'new') throw new ProviderUnavailable();
    if (!this.startup) this.startup = this.start();
    return this.startup;
  }
  private async start(): Promise<void> {
    const options = { deadline: now() + this.config.startup_timeout, signal: this.startupController.signal };
    try {
      await bounded(check_files(this.config), options);
      const creating = Promise.resolve().then(() => this.factory(this.config));
      void creating.then(pool => { this.pool = pool; if (this.state !== 'new') void this.end_driver(pool).catch(() => {}); }, () => {});
      this.pool = await bounded(creating, options);
      const connecting = this.pool.connect();
      let abandoned = false;
      let seen: PgClient | undefined;
      let released = false;
      const release = (): void => { if (seen && !released) { released = true; seen.release(abandoned); } };
      void connecting.then(client => { seen = client; if (abandoned) { try { release(); } catch {} } }, () => {});
      await bounded(connecting, options, () => { abandoned = true; release(); });
      release();
      if (this.state !== 'new') throw new ProviderUnavailable();
      this.state = 'open';
    } catch (error) {
      this.state = 'closed';
      try { await bounded(this.end_driver(), { deadline: now() + this.config.close_timeout }); } catch {}
      if (error instanceof UnsupportedCapability || error instanceof InvalidRequest) throw error;
      throw new ProviderUnavailable();
    }
  }
  async withLease<T>(options: LeaseOptions, body: (client: PgClient, signal: AbortSignal) => Promise<T>): Promise<T> {
    check_options(options);
    if (this.state !== 'open' || !this.pool) throw new ProviderUnavailable();
    if (context.getStore()?.has(this)) throw new InvalidRequest();
    if (this.work.size + this.connecting.size >= this.config.max_size + this.config.max_waiting) throw new ProviderUnavailable();
    let finish!: () => void;
    const item: Work = { controller: new AbortController(), done: new Promise(resolve => { finish = resolve; }), finish: () => finish(), released: false };
    this.work.add(item);
    const relay = (): void => item.controller.abort(abort_error());
    options.signal?.addEventListener('abort', relay, { once: true });
    const release = (destroy: boolean): void => {
      if (!item.released && item.client) { item.released = true; item.client.release(destroy); }
    };
    let acquiring = true;
    let failed = false;
    try {
      const acquireDeadline = Math.min(options.deadline, now() + this.config.acquire_timeout);
      let pending: Promise<PgClient>;
      try { pending = this.pool.connect(); } catch { throw new ProviderUnavailable(); }
      let abandoned = false;
      let settled = false;
      const tracked = pending.then(client => {
        item.client = client;
        if (abandoned) { try { release(false); } catch {} }
      }, () => {}).finally(() => { settled = true; this.connecting.delete(tracked); });
      // Pending abandoned checkouts retain an admission slot until the driver settles.
      try {
        await bounded(pending, { deadline: acquireDeadline, signal: item.controller.signal }, () => { abandoned = true; release(false); });
      } catch (error) {
        abandoned = true; if (!settled) this.connecting.add(tracked);
        if (error instanceof DeadlineExceeded && now() < options.deadline) throw new ProviderUnavailable();
        if (error instanceof DOMException && error.name === 'AbortError') throw error;
        if (error instanceof DeadlineExceeded) throw error;
        throw new ProviderUnavailable();
      }
      acquiring = false;
      if (this.state !== 'open') throw new ProviderUnavailable();
      const client: PgClient = {
        query: config => item.released ? Promise.reject(new ProviderUnavailable()) : item.client!.query(config),
        getTransactionStatus: () => item.released ? null : item.client!.getTransactionStatus(),
        release: destroy => release(destroy ?? false),
      };
      const running = context.run(new Set([...(context.getStore() ?? []), this]), () => body(client, item.controller.signal));
      return await bounded(running, { deadline: options.deadline, signal: item.controller.signal }, () => { try { release(true); } finally { item.controller.abort(abort_error()); } });
    } catch (error) {
      failed = true;
      throw error;
    } finally {
      options.signal?.removeEventListener('abort', relay);
      try { release(item.controller.signal.aborted || acquiring); }
      catch { if (!failed && !acquiring) throw new ProviderUnavailable(); }
      finally { this.work.delete(item); item.finish(); }
    }
  }
  async close(): Promise<void> {
    if (context.getStore()?.has(this)) throw new InvalidRequest();
    return this.closing ??= this.finish_close();
  }
  private async finish_close(): Promise<void> {
    this.state = 'closing'; this.startupController.abort();
    const deadline = now() + this.config.close_timeout;
    for (const item of this.work) item.controller.abort(abort_error());
    let failed = false;
    try { await bounded(Promise.allSettled([...this.work].map(item => item.done)), { deadline }); } catch { failed = true; }
    try { await bounded(Promise.allSettled([...this.connecting]), { deadline: Math.min(deadline, now() + this.config.close_timeout / 2) }); } catch { failed = true; }
    try { await bounded(this.end_driver(), { deadline }); } catch { failed = true; }
    this.state = 'closed';
    if (failed) throw new ProviderUnavailable();
  }
}
