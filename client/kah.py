#!/usr/bin/env python3
"""kah: drive a running Kenshi through the Kenshi Automation Harness.

  kah on | off                       enable/disable the harness (enabled.flag; autosave
                                     is off and the game runs unfocused while enabled)
  kah autoload <save>                load <save> as soon as the main menu is up
  kah wait-world [timeout_s]         wait until a save is loaded and the world runs
  kah help                           every command the running game knows (incl. mods)
  kah <command> [args...]            send one command, print the reply

Built-in commands:
  status                                  phase (menu|loading|world), save, speed, squad
  load <save> | save <name>
  speed <0|0.5..50>                       0 pauses
  chars [radius] | traders [radius]       characters near the player | real traders
  benches [radius]                        crafting benches, their queue and contents
  find <character|squad|item|weapon|armour|container> <text>
  spawn <template> <faction> [near <npc> | at x y z] [count n] [dist m] [target <npc>] [size <mult>]
  where|inv|hp|sections|select|recruit|kill <npc>  (inv: inventory JSON incl. worn items;
                                          sections: inventory sections and their items)
  stat <npc> <stat> | setstat <npc> <stat> <value> | weight <npc>
  iteminfo|equip|unequip <npc> "<item name>"
  teleport <npc> <npc2 | x y z> [dist m]
  ko <npc> [seconds] | health <npc> <percent> | hunger <npc> <0..300>
  attack <attacker> <target> | give <npc> <item> [n] | relation <npc> <-100..100>
  money <npc> <delta> | buy <buyer> <seller> <item> <price>
  stash <item> <n> [near <npc>]
  transfer <from npc> <to npc> <item> | craftfinish <npc> <item> [at <bench>]
  packput <npc> <pack> <item> [n] | packweight <npc> <pack>
<npc> is a name (exact match nearest the player wins), #serial, @player or @selected.

The harness folder is the installed mod folder (Kenshi\\mods\\AutomationHarness):
set KAH_DIR to it, or pass --dir <path> first. Works from Windows and WSL.
"""
import os
import sys
import time

DEFAULT_DIRS = [
    r'C:\Program Files (x86)\Steam\steamapps\common\Kenshi\mods\AutomationHarness',
    r'D:\Steam\steamapps\common\Kenshi\mods\AutomationHarness',
    r'D:\SteamLibrary\steamapps\common\Kenshi\mods\AutomationHarness',
]


def to_local(path):
    """C:\\x\\y -> /mnt/c/x/y when running under WSL/Linux."""
    if os.name == 'nt' or len(path) < 2 or path[1] != ':':
        return path
    return '/mnt/' + path[0].lower() + path[2:].replace('\\', '/')


def harness_dir(argv):
    given, rest = None, argv
    if len(argv) >= 2 and argv[0] == '--dir':
        given, rest = argv[1], argv[2:]
    elif os.environ.get('KAH_DIR'):
        given = os.environ['KAH_DIR']
    if given:
        if not os.path.isdir(to_local(given)):
            sys.exit('no such folder: %s' % given)
        return to_local(given), rest
    for d in DEFAULT_DIRS:
        if os.path.isdir(to_local(d)):
            return to_local(d), argv
    sys.exit('harness folder not found: set KAH_DIR or pass --dir <Kenshi\\mods\\AutomationHarness>')


def send(d, cmd, args, timeout=20):
    flag, inbox, outbox = (os.path.join(d, n) for n in ('enabled.flag', 'inbox.txt', 'outbox.txt'))
    if not os.path.exists(flag):
        sys.exit('harness is off: run "kah on" (before launching Kenshi)')
    if any('\t' in a or '\n' in a for a in args):
        sys.exit('arguments may not contain tabs or newlines')
    deadline = time.time() + timeout
    while os.path.exists(inbox):
        if time.time() > deadline:
            sys.exit('previous command still unread: is Kenshi running?')
        time.sleep(0.2)
    cid = 'k%d' % int(time.time() * 1000)
    tmp = inbox + '.tmp'
    with open(tmp, 'w', newline='\n') as f:
        f.write('\t'.join([cid, cmd] + args) + '\n')
    os.replace(tmp, inbox)
    while time.time() < deadline:
        if os.path.exists(outbox):
            with open(outbox, encoding='utf-8', errors='replace') as f:
                for line in f:
                    parts = line.rstrip('\n').split('\t', 2)
                    if parts[0] == cid and len(parts) == 3:
                        return parts[1] == 'ok', parts[2]
        time.sleep(0.2)
    sys.exit('no answer within %ds (Kenshi not running or stuck loading?)' % timeout)


def main():
    d, argv = harness_dir(sys.argv[1:])
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd == 'on':
        open(os.path.join(d, 'enabled.flag'), 'w').close()
        print('harness on (%s)' % d)
        return 0
    if cmd == 'off':
        try:
            os.remove(os.path.join(d, 'enabled.flag'))
        except FileNotFoundError:
            pass
        print('harness off')
        return 0
    if cmd == 'autoload':
        if len(args) != 1:
            sys.exit('usage: kah autoload <save>')
        with open(os.path.join(d, 'autoload.txt'), 'w', newline='') as f:
            f.write(args[0])
        print('autoload %s' % args[0])
        return 0
    if cmd == 'wait-world':
        limit = float(args[0]) if args else 300
        end = time.time() + limit
        detail = ''
        while time.time() < end:
            try:
                ok, detail = send(d, 'status', [], timeout=10)
            except SystemExit:
                ok, detail = False, 'no answer (loading?)'
            if ok and 'phase=world' in detail:
                print(detail)
                return 0
            time.sleep(2)
        print('world not ready after %ds: %s' % (limit, detail))
        return 1
    ok, detail = send(d, cmd, args)
    print(('' if ok else 'ERROR: ') + detail)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
