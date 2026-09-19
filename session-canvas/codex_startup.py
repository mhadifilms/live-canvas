"""Codex Desktop startup through managed AGENTS instructions, without hook trust edits."""
import os
from pathlib import Path
import shlex
import sys
import canvas

BEGIN = '<!-- BEGIN LIVE CANVAS STARTUP -->'
END = '<!-- END LIVE CANVAS STARTUP -->'


def plan(user_home):
    import install_clients as legacy
    base = Path(os.environ.get('CODEX_HOME', str(user_home / '.codex'))) if user_home == Path.home().resolve() else user_home / '.codex'
    path = base / 'AGENTS.md'
    if path.is_symlink(): raise ValueError('Refusing to replace symlinked Codex instructions')
    original = path.read_text() if path.exists() else ''
    if original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1:
        raise ValueError('Malformed Live Canvas instruction block; file preserved')
    manifest_path=base/'.live-canvas-startup.json'
    manifest=canvas.read_json(manifest_path,{})
    if manifest and manifest.get('source')!=str(legacy.SKILL):raise ValueError('Startup instructions belong to another installation')
    if manifest and BEGIN in original and manifest.get('block')!=BEGIN+original.split(BEGIN,1)[1].split(END,1)[0]+END:raise ValueError('Startup instructions were edited; preserving them for review')
    prefix = shlex.join([sys.executable, str(legacy.SKILL / 'scripts/live_canvas.py')])
    block = BEGIN + '\n## Live Canvas\n\nUse one persistent Live Canvas per foreground task. Before task work on the first user turn, read the live-canvas skill and run `' + prefix + ' auto-open claim` using the actual CODEX_THREAD_ID supplied by Codex. Never invent an identity; skip in subagents/background runs or if no actual identity is available. Respect stop and auto-open off. If should_open is true, start with the returned claim, find and focus an existing browser tab for the returned URL, and open a new tab only when none exists. Acknowledge only completed opening or an observed existing view; release failed or queued attempts. Do not create duplicate canvases. Avoid completion-summary Markdown files and alternate canvas tools unless explicitly requested. Visible replies are captured automatically. Keep useful authored work in that same canvas; inspect user feedback at normal milestones rather than polling or creating extra turns.\n' + END
    if BEGIN in original:
        before,rest=original.split(BEGIN,1);_,after=rest.split(END,1);updated=before+block+after
    else: updated=original.rstrip()+'\n\n'+block+'\n'
    skill=base/'skills/live-canvas'
    if skill.parent.is_symlink():raise ValueError('Refusing symlinked Codex skills directory')
    same=skill.is_symlink() and skill.resolve()==legacy.SKILL.resolve()
    if (skill.exists() or skill.is_symlink()) and not same:raise ValueError('Existing Codex skill preserved')
    # Preflight legacy removal. Only previously-owned, unchanged entries may be removed.
    old = legacy.plan(user_home, 'codex', uninstall=True)
    return {'client':'codex','startup_instruction':True,'base':base,'config_path':path,'skill_path':skill,'original':original,'updated':updated,
        'installed':same and original==updated,'same_skill':same,'legacy':old,'manifest':manifest,'manifest_path':manifest_path,'block':block,'created_skill':manifest.get('created_skill',not same)}


def apply(item):
    import install_clients as legacy
    base=item['base'];base.mkdir(parents=True,exist_ok=True,mode=0o700)
    canvas.atomic_json(item['manifest_path'],{'source':str(legacy.SKILL),'created_skill':item['created_skill'],'block':item['block']})
    if item['original']!=item['updated']:
        legacy.backup(item['config_path'],base)
        canvas.atomic_bytes(item['config_path'],item['updated'].encode())
    # Remove our obsolete hooks while preserving unrelated hooks and their trust.
    if item['legacy']['manifest']:legacy.apply(item['legacy'])
    item['skill_path'].parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not item['skill_path'].exists():item['skill_path'].symlink_to(legacy.SKILL,target_is_directory=True)
    return {'client':'codex','changed':item['original']!=item['updated'],'config':str(item['config_path']),
        'readiness':'startup_instruction_installed','next_step':'Start or resume a Codex Desktop task. Canvas startup runs on its first user turn; no CLI hook trust step is needed.'}


def uninstall_plan(user_home):
    item=plan(user_home)
    original=item['original'];updated=original
    if BEGIN in original:
        before,rest=original.split(BEGIN,1);_,after=rest.split(END,1)
        updated=before.rstrip()+after
    item.update(updated=updated,uninstall=True)
    return item


def uninstall(item):
    import install_clients as legacy
    if item['original']!=item['updated']:
        legacy.backup(item['config_path'],item['base'])
        canvas.atomic_bytes(item['config_path'],item['updated'].encode())
    if item['legacy']['manifest']:legacy.apply(item['legacy'])
    if item['created_skill'] and item['same_skill'] and item['skill_path'].is_symlink():item['skill_path'].unlink()
    item['manifest_path'].unlink(missing_ok=True)
    return {'client':'codex','changed':item['original']!=item['updated'],'status':'uninstalled'}
