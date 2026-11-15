#!/usr/bin/env node
/**
 * Trailblazer CLI Runner (npm / npx distribution)
 * Zero-dependency: Spawns the bundled Python 3 engine.
 */

const { spawn } = require('child_process');
const path = require('path');

const scriptPath = path.join(__dirname, '..', 'scripts', 'compile.py');
const args = [scriptPath, ...process.argv.slice(2)];

const child = spawn('python3', args, {
  stdio: 'inherit',
  env: process.env
});

child.on('error', (err) => {
  if (err.code === 'ENOENT') {
    console.error('Error: "python3" was not found in your PATH.');
    console.error('Trailblazer requires Python 3.8+ to be installed.');
  } else {
    console.error(`Failed to execute Trailblazer: ${err.message}`);
  }
  process.exit(1);
});

child.on('exit', (code) => {
  process.exit(code !== null ? code : 0);
});
