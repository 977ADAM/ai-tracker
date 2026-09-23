import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { commands, startProcesses } from './run-local.mjs';

test('dev and built modes bind the web process to loopback', () => {
  const [python, dev] = commands('dev');
  const [, built] = commands('start');
  assert.deepEqual(python.args, ['run', 'ai-tracker']);
  assert.match(dev.args.join(' '), /127\.0\.0\.1/);
  assert.equal(built.env.HOST, '127.0.0.1');
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
