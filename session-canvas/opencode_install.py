"""Reversible global OpenCode plugin and skill install."""
import json
import os
from pathlib import Path
import sys
import canvas


def plan(user_home, uninstall=False):
    import install_clients as installer
    base = user_home / '.config/opencode'
    if user_home == Path.home().resolve() and os.environ.get('XDG_CONFIG_HOME'):
        base = Path(os.environ['XDG_CONFIG_HOME']) / 'opencode'
    plugin = base / 'plugins/live-canvas.mjs'
    skill = base / 'skills/live-canvas'
    manifest_path = base / '.live-canvas-install.json'
    for path in (plugin, plugin.parent, skill.parent):
        if path.is_symlink(): raise ValueError('Refusing symlinked OpenCode plugin/config directory')
    manifest = installer.load(manifest_path, None)
    original = plugin.read_text() if plugin.exists() else None
    same_skill = skill.is_symlink() and skill.resolve() == installer.SKILL.resolve()
    if (skill.exists() or skill.is_symlink()) and not same_skill: raise ValueError('Existing OpenCode skill preserved')
    if manifest and (manifest.get('source') != str(installer.SKILL) or manifest.get('plugin') != original):
        raise ValueError('OpenCode plugin changed since installation; preserve it and review first')
    if original is not None and not manifest: raise ValueError('Unowned OpenCode plugin preserved')
    source = (installer.HERE / 'opencode-plugin.mjs').read_text()
    desired = source.replace('__PYTHON__', json.dumps(sys.executable)).replace('__BRIDGE__', json.dumps(str(installer.HERE / 'opencode_bridge.py'))).replace('__LAUNCHER__', json.dumps(str(installer.SKILL / 'scripts/live_canvas.py')))
    return {'client':'opencode','base':base,'config_path':plugin,'manifest_path':manifest_path,'skill_path':skill,'same_skill':same_skill,
        'original':original,'updated':None if uninstall else desired,'manifest':manifest,'installed':bool(manifest and same_skill and original==desired),'uninstall':uninstall}


def apply(item):
    import install_clients as installer
    path=item['config_path']; path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if item['uninstall']:
        if not item['manifest']: return {'client':'opencode','changed':False}
        installer.backup(path,item['base']);path.unlink(missing_ok=True)
        if item['same_skill']:item['skill_path'].unlink()
        item['manifest_path'].unlink(missing_ok=True)
    else:
        installer.backup(path,item['base']) if item['original'] != item['updated'] else None
        canvas.atomic_json(item['manifest_path'],{'source':str(installer.SKILL),'plugin':item['updated']})
        canvas.atomic_bytes(path,item['updated'].encode())
        item['skill_path'].parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if not item['same_skill']:item['skill_path'].symlink_to(installer.SKILL,target_is_directory=True)
    return {'client':'opencode','changed':item['original']!=item['updated'],'config':str(path)}
