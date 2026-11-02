#!/usr/bin/env bash
# Production publication from a trusted main workflow; no asset replacement.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
[[ ${VLC_PUBLICATION_APPROVED:-} == production-pair-reviewed && ${GITHUB_ACTIONS:-} == true &&
   ${GITHUB_REF:-} == refs/heads/main ]] || {
  echo 'Publication locked: requires the authorized main production workflow' >&2; exit 1;
}
candidate=$(realpath -- "${1:?artifact directory}")
version=$(python3 "$root/scripts/production.py" prepare "$candidate")
cd "$candidate"
[[ -s provenance.intoto.jsonl ]] || { echo 'Missing signed publication attestation' >&2; exit 1; }
for asset in ./*.tar.zst release.json current-runtime.json; do gh attestation verify "$asset" --repo "$GITHUB_REPOSITORY"; done
sha=$(python3 -c 'import json;print(json.load(open("inputs.json"))["upstream_sha"])')
if gh api "repos/$GITHUB_REPOSITORY/git/ref/tags/$version" > /dev/null 2> tag-error.log; then
  echo 'Tag already exists; refusing replacement' >&2; exit 1
else
  grep -q 'HTTP 404' tag-error.log || { cat tag-error.log >&2; exit 1; }
fi
cat > notes.md <<NOTES
Community VLC 4 development build; not an official VideoLAN binary release.
Upstream source: $sha. KDE SDK/Platform 6.11; Qt/KF libraries come from the runtime.

Both native architectures and their exact bytes passed the production pair gate,
subject to any explicitly listed WAIVED exception below. See release.json,
inputs.json and build-*.json for exact source, patches, Qt content and deployment pins.
The published attestation signs these bytes in the publication workflow; it does
not claim that promotion rebuilt VLC. Original build run: $SOURCE_RUN_ID.

Checksums: SHA256SUMS; byte sizes: sizes.json.
Recipe: $GITHUB_SERVER_URL/$GITHUB_REPOSITORY/tree/$GITHUB_SHA
Publication run: $GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID
NOTES
python3 - <<'PYNOTES'
import json
from pathlib import Path
summary=json.loads(Path('verification-pair.json').read_text())
with Path('notes.md').open('a') as notes:
    notes.write('\nDownstream source corrections are recorded in inputs.json and embedded patches/manifest.json.\n')
    if summary['automated_status']=='WAIVED':
        notes.write('\nKNOWN UPSTREAM ISSUE — automated verification WAIVED:\n')
        for issue in summary['known_issues']:
            notes.write(f"- {issue['architecture']}: X11 rapid OpenUri/Quit assertion crash; "
                        f"{issue['id']}, expires {issue['expires_at']}; source {issue['source_commit']}.\n")
PYNOTES
assets=(./*.tar.zst SHA256SUMS sizes.json inputs.json build-x86_64.json build-aarch64.json
        verification-x86_64.json verification-aarch64.json verification-pair.json release.json current-runtime.json provenance.intoto.jsonl)
for log in xcb-gui-openuri-quit-rapid-*.log; do
  if [[ -f $log ]]; then assets+=("$log"); fi
done
# Re-evaluate the live UTC waiver immediately before the outward action.
"$root/scripts/verify-artifacts.sh" "$candidate"
gh release create "$version" --repo "$GITHUB_REPOSITORY" --target "$GITHUB_SHA" \
  --draft --prerelease --title "VLC $version" --notes-file notes.md "${assets[@]}"
check=$(mktemp -d)
trap 'rm -rf "$check"' EXIT
gh release download "$version" --repo "$GITHUB_REPOSITORY" --dir "$check"
cmp release.json "$check/release.json"
for asset in "${assets[@]}"; do cmp "$asset" "$check/${asset##*/}"; done
[[ $(find "$check" -mindepth 1 -maxdepth 1 -type f | wc -l) -eq ${#assets[@]} ]]
(cd "$check"; sha256sum -c "$candidate/SHA256SUMS")
python3 - "$check" <<'PYSIZE'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);data=json.loads((root/'release.json').read_text())
assert all((root/a['name']).stat().st_size==a['size'] for a in data['assets'].values()), 'uploaded size mismatch'
PYSIZE
# A slow upload must not carry an expired exception into publication.
"$root/scripts/verify-artifacts.sh" "$candidate"
gh release edit "$version" --repo "$GITHUB_REPOSITORY" --draft=false
