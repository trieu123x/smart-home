#!/usr/bin/env node
// PreToolUse hook for the Bash and PowerShell tools.
// Denies commands that are almost never intended and asks before commands that
// destroy work or reach outside the repo. Edit RULES to fit your project.
//
// This is a safety net, not a security boundary: a determined command can be
// written in a form these patterns miss. Keep permissions.deny in settings.json too.

import { readFileSync } from 'node:fs';

// Tokens that make a recursive delete catastrophic.
const DANGEROUS_TARGETS = new Set([
  '/', '/*', '~', '~/', '~/*', '$HOME', '$HOME/', '${HOME}', '.', './', '*', '..', '../',
  '$env:USERPROFILE', '$env:HOMEDRIVE', '%USERPROFILE%', '\\', 'C:', 'C:\\', 'C:/', 'C:\\*', 'C:/*',
]);

const RECURSIVE_DELETE = [
  /\brm\s+(?:-\S*\s+)*-\S*[rR]/,                                   // rm -rf, rm -r -f, rm -fr
  /\brm\s+(?:\S+\s+)*--recursive\b/,
  /\b(?:Remove-Item|ri|rm|del|erase|rd|rmdir)\b[^|;]*\s-Recurse\b/i,  // PowerShell
  /\b(?:rd|rmdir)\s+\/s\b/i,                                       // cmd.exe
];

const SECRET_READERS =
  /\b(?:cat|type|more|less|head|tail|bat|grep|rg|awk|sed|Get-Content|gc|Select-String|findstr|base64|xxd|od)\b/i;
const SECRET_FILE =
    /(?:^|[\s'"=\/\\])(?:id_rsa|id_ed25519|[\w.-]+\.pem|[\w.-]+\.key)(?=$|[\s'"|;&)])/i;

/** Each rule: [decision, test(command) => boolean, reason]. First match wins, deny before ask. */
const RULES = [
  ['deny', (c) => RECURSIVE_DELETE.some((re) => re.test(c)) && tokens(c).some((t) => DANGEROUS_TARGETS.has(t)),
    'Recursive delete of a root, home, current or parent directory is blocked. Delete specific paths instead.'],
  ['deny', (c) => /\b(?:curl|wget|iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b[^|]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh|iex|Invoke-Expression|python\d?|node)\b/i.test(c),
    'Piping a download straight into a shell is blocked. Download the script, show it, and let the user decide.'],
  ['deny', (c) => /\bmkfs(?:\.\w+)?\b|\bdd\b[^|;]*\bof=\/dev\/|\bformat\s+[a-z]:/i.test(c) || /\bFormat-Volume\b/i.test(c),
    'Disk formatting and raw device writes are blocked.'],
  ['deny', (c) => SECRET_READERS.test(c) && SECRET_FILE.test(c),
    'Reading secret files (.env, private keys) through the shell is blocked. Ask the user for the specific value you need.'],

  ['ask', (c) => /\bgit\s+push\b[^|;&]*(?:\s--force(?:-with-lease)?\b|\s-f\b|\s\+\S)/.test(c),
    'Force push rewrites remote history.'],
  ['ask', (c) => /\bgit\s+(?:reset\s+--hard|clean\s+-\S*f|checkout\s+(?:--\s+)?\.(?:\s|$)|restore\s+(?:--\S+\s+)*\.(?:\s|$)|stash\s+(?:drop|clear)|branch\s+-D)/.test(c),
    'This git command discards uncommitted work or branches.'],
  ['ask', (c) => /\b(?:DROP\s+(?:DATABASE|SCHEMA|TABLE)|TRUNCATE(?:\s+TABLE)?\s+\w)/i.test(c) || /\bDELETE\s+FROM\s+[\w."]+\s*(?:;|$|["'])/i.test(c),
    'Destructive SQL (DROP/TRUNCATE/DELETE without WHERE).'],
  ['ask', (c) => /\b(?:npm|pnpm|yarn)\s+publish\b|\bmvn\b[^|;]*\bdeploy\b|\bgradlew?\b[^|;]*\bpublish\b|\bcargo\s+publish\b|\btwine\s+upload\b/i.test(c),
    'Publishing a package is outward-facing and hard to undo.'],
  ['ask', (c) => /\bterraform\s+(?:destroy|apply)\b|\bkubectl\s+delete\b|\bdocker\s+(?:system|volume)\s+prune\b|\bdocker\s+compose\s+down\b[^|;]*\s-v\b/i.test(c),
    'This command changes or deletes infrastructure or stored data.'],
];

function tokens(command) {
  return command.split(/\s+/).map((t) => t.replace(/^['"]|['"]$/g, '').replace(/;$/, ''));
}

function main() {
  let input;
  try {
    input = JSON.parse(readFileSync(0, 'utf8'));
  } catch {
    return; // Unreadable input: let the normal permission flow decide.
  }
  const command = input?.tool_input?.command;
  if (typeof command !== 'string' || command.length === 0) return;

  for (const decision of ['deny', 'ask']) {
    const rule = RULES.find(([d, test]) => d === decision && test(command));
    if (rule) {
      process.stdout.write(JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: decision,
          permissionDecisionReason: `[guard-commands] ${rule[2]}`,
        },
      }));
      return;
    }
  }
}

main();
