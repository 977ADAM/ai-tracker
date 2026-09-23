import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { commands, startProcesses } from './run-local.mjs';

test('dev and built modes bind the web process to loopback', () => {
  const [python, dev] = commands('dev');
  const [, built] = commands('start');
  assert.deepEqual(python.args, ['run', 'ai-tracker']);
  assert.match(dev.args.join(' '), /127\.0\.0\.1/);
  assert.equal(built.env.HOST, '127.0.0.1');
  assert.equal(built.env.ORIGIN, 'http://127.0.0.1:5173');
});

test('stopping the runner terminates both children', async () => {
  const childSpec = { command: process.execPath, args: ['-e', 'setInterval(() => {}, 1000)'] };
  const running = startProcesses([childSpec, childSpec], { stdio: 'ignore' });
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(running.children.length, 2);
  assert.ok(running.children.every((child) => child.exitCode === null));
  running.stop();
  await running.done;
  assert.ok(running.children.every((child) => child.exitCode !== null || child.signalCode !== null));
});

test('a missing executable stops the other child and exits nonzero', async () => {
  const running = startProcesses([
    { command: 'definitely-missing-ai-tracker-command', args: [] },
    { command: process.execPath, args: ['-e', 'setInterval(() => {}, 1000)'] }
  ], { stdio: 'ignore' });
  let timeout;
  const code = await Promise.race([
    running.done,
    new Promise((_, reject) => { timeout = setTimeout(() => { running.stop(); reject(new Error('runner did not finish')); }, 1000); })
  ]).finally(() => clearTimeout(timeout));
  assert.equal(code, 1);
  assert.ok(running.children[1].exitCode !== null || running.children[1].signalCode !== null);
});
