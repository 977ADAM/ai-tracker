import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve } from 'node:path';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const backend = resolve(root, 'backend');
const frontend = resolve(root, 'frontend');

export function commands(mode) {
  if (mode !== 'dev' && mode !== 'start') throw new Error('Unknown run mode');
  const python = { command: 'uv', args: ['run', 'ai-tracker'], cwd: backend, env: {} };
  const web = mode === 'dev'
    ? { command: process.execPath, args: ['../node_modules/vite/bin/vite.js', 'dev', '--host', '127.0.0.1', '--port', '5173', '--strictPort'], cwd: frontend, env: {} }
    : { command: process.execPath, args: ['build/index.js'], cwd: frontend, env: { HOST: '127.0.0.1', PORT: '5173', ORIGIN: 'http://127.0.0.1:5173' } };
  return [python, web];
}

export function startProcesses(specs, { stdio = 'inherit' } = {}) {
  const children = specs.map((spec) => spawn(spec.command, spec.args, {
    cwd: spec.cwd ?? root, stdio, env: { ...process.env, ...spec.env }
  }));
  let stopping = false;
  let exitCode = 0;
  function stop() {
    if (stopping) return;
    stopping = true;
    for (const child of children) {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
    }
  }
  const done = new Promise((resolveDone) => {
    let remaining = children.length;
    children.forEach((child, index) => {
      child.on('error', (error) => {
        exitCode = 1;
        console.error(`Не удалось запустить ${index === 0 ? 'Python API' : 'SvelteKit'}: ${error.code || 'ошибка процесса'}`);
        stop();
      });
      child.on('close', (code, signal) => {
        if (!stopping) {
          exitCode = code || (signal ? 1 : 0);
          if (exitCode) console.error('Один из локальных сервисов остановился. Проверьте, не занят ли его порт.');
          stop();
        }
        remaining -= 1;
        if (remaining === 0) resolveDone(exitCode);
      });
    });
  });
  return { children, stop, done };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const running = startProcesses(commands(process.argv[2] || 'dev'));
  process.on('SIGINT', running.stop);
  process.on('SIGTERM', running.stop);
  running.done.then((code) => { process.exitCode = code; });
}
