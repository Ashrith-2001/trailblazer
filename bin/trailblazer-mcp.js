#!/usr/bin/env node
/**
 * Trailblazer MCP Server Runner (npm / npx distribution)
 * Zero-dependency: Pipes stdio to the Python MCP server.
 */

const { spawn } = require('child_process');
const path = require('path');

const serverPath = path.join(__dirname, '..', 'mcp-server', 'server.py');
const child = spawn('python3', [serverPath, ...process.argv.slice(2)], {
  stdio: ['pipe', 'pipe', 'inherit'],
  env: process.env
});

child.on('error', (err) => {
  if (err.code === 'ENOENT') {
    console.error('Error: "python3" was not found in your PATH.');
    console.error('Trailblazer requires Python 3.8+ to be installed.');
  } else {
    console.error(`Failed to launch Trailblazer MCP server: ${err.message}`);
  }
  process.exit(1);
});

// Stdio bidirectional pipe for Model Context Protocol JSON-RPC
process.stdin.pipe(child.stdin);
child.stdout.pipe(process.stdout);

child.on('exit', (code) => {
  process.exit(code !== null ? code : 0);
});
