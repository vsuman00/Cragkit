/** Run with: node postgres.mjs /absolute/private/runtime.json /absolute/request.json */
import { readFile, lstat } from 'node:fs/promises';
import { parse_request, parse_scope } from 'cragkit/contracts';
import { PoolResource, PostgresRetriever, parse_pool_config, now } from 'cragkit/postgres';

async function main(configPath, inputPath) {
  const info = await lstat(configPath);
  if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o077) !== 0) {
    throw Error('Private configuration required');
  }
  const config = parse_pool_config(JSON.parse(await readFile(configPath, 'utf8')));
  const supplied = JSON.parse(await readFile(inputPath, 'utf8'));
  const request = parse_request(supplied.request);
  // Trusted scope comes from application authorization, outside agent-editable input.
  const scope = parse_scope(supplied.scope);
  const resource = new PoolResource(config);
  try {
    await resource.open();
    const result = await new PostgresRetriever(resource).retrieve(request, {scope, deadline: now() + 20});
    console.log(JSON.stringify(result));
  } finally {
    await resource.close();
  }
}

try {
  if (process.argv.length !== 4) throw Error('Expected configuration and input paths');
  await main(process.argv[2], process.argv[3]);
} catch {
  console.error(JSON.stringify({state:'failed', code:'example_failed'}));
  process.exitCode = 1;
}
