"""One explicitly approved, expiring exception; raw checks are never modified."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re

POLICY=Path(__file__).with_name('x11-waiver.json')
ASSERTION=re.compile(r"\bCompositorX11::quickWindow\(\)(?: const)?: Assertion [`']m_qmlView['`] failed\.\s*$")


def utc(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('UTC timestamp required')
    return result.astimezone(timezone.utc)


def evaluate(report,required,directory,now=None):
    """Use real UTC in production; injectable time is only for focused unit tests."""
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('Aware UTC time required')
    decision=dict(outcome='FAIL',waiver=None,reason='Mandatory verification incomplete')
    checks=report['checks'];names=[c['name'] for c in checks]
    if len(names)!=len(set(names)):return decision
    indexed={c['name']:c for c in checks}
    if not required or not required<=indexed.keys() or any(not indexed[n]['mandatory'] for n in required):return decision
    # The caller's explicit policy determines release requirements, including
    # when reading older reports whose diagnostic flags were mandatory.
    failed=[indexed[n] for n in required if indexed[n]['status']!='pass']
    failed += [c for c in checks if c['name']=='verification-driver' and c['status']!='pass']
    if not failed:return dict(outcome='PASS',waiver=None,reason='All mandatory checks passed')
    policy_bytes=POLICY.read_bytes();policy=json.loads(policy_bytes)
    decision['reason']='No applicable enabled waiver'
    if (policy['enabled'] is not True or report['architecture']!=policy['architecture']
            or len(failed)!=1 or failed[0]['name']!=policy['test'] or failed[0]['status']!='fail'):
        return decision
    audit=dict(id=policy['id'],source_commit=report['upstream_sha'],architecture=report['architecture'],
               test=policy['test'],effective_from=policy['effective_from'],expires_at=policy['expires_at'],
               evaluated_at=now.astimezone(timezone.utc).isoformat().replace('+00:00','Z'),
               policy_sha256=hashlib.sha256(policy_bytes).hexdigest(),decision='FAIL')
    decision['waiver']=audit
    if not utc(policy['effective_from'])<=now<utc(policy['expires_at']):
        decision['reason']='Waiver outside its effective UTC interval';return decision
    if not re.fullmatch('[0-9a-f]{40}',report['upstream_sha']):return decision
    evidence=report.get('rapid_quit_evidence',{})
    # Preserve the original playback prerequisites as well as the crash signature.
    if (not re.match(r'exit=134;',failed[0].get('detail',''))
            or evidence.get('ran') is not True or evidence.get('test')!=policy['test']
            or type(evidence.get('exit_code')) is not int or evidence['exit_code']!=policy['exit_code']
            or not all(evidence.get(k) is True for k in ('playing','rendering','surface','open_uri','no_other_fatal'))):
        decision['reason']='Missing or incorrect execution/playback evidence';return decision
    expected=policy['test']+'-'+report['architecture']+'.log'
    if evidence.get('log_name')!=expected:
        decision['reason']='Missing or unsafe diagnostic log';return decision
    file=Path(directory)/expected
    if file.is_symlink() or not file.is_file():
        decision['reason']='Missing diagnostic log';return decision
    data=file.read_bytes();checksum=hashlib.sha256(data).hexdigest()
    if evidence.get('log_sha256')!=checksum:
        decision['reason']='Diagnostic log hash mismatch';return decision
    text=data.decode('utf-8',errors='replace')
    assertions=[line for line in text.splitlines() if re.search(r'assertion\b.*\bfailed',line,re.I)]
    if (not assertions or any(not ASSERTION.search(line) or len(re.findall(r'\bassertion\b',line,re.I))!=1 for line in assertions)
            or re.search(r'SIGSEGV|Segmentation fault',text)):
        decision['reason']='Missing or different crash signature';return decision
    audit.update(decision='WAIVED',exit_code=evidence['exit_code'],log_name=expected,
                 log_sha256=checksum,assertion_lines=assertions,
                 known_issue='Upstream X11 rapid OpenUri/Quit compositor assertion crash')
    return dict(outcome='WAIVED',waiver=audit,reason=audit['known_issue'])
