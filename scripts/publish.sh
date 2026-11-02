#!/usr/bin/env bash
# Publication remains locked until native CI and manual regression evidence are reviewed.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
"$root/scripts/verify-artifacts.sh" "${1:?artifact directory}"
# A future enabling change must explicitly record reviewed manual/CI evidence.
[[ ${VLC_PUBLICATION_APPROVED:-} == phase-2-reviewed ]] || {
  echo "Publication locked: native CI and manual verification require review" >&2; exit 1;
}
cd "$1"
version=$(python3 -c 'import json;print((lambda d: d.get("artifact_version",d["version"]))(json.load(open("inputs.json"))))')
sha=$(python3 -c 'import json;print(json.load(open("inputs.json"))["upstream_sha"])')
# Never edit assets, delete a release, or use --clobber. An incomplete draft is a
# manual investigation, not permission to replace potentially published bytes.
if gh api "repos/$GITHUB_REPOSITORY/git/ref/tags/$version" > /dev/null 2> tag-error.log; then
  echo 'Tag already exists; refusing replacement' >&2; exit 1
else
  grep -q 'HTTP 404' tag-error.log || { cat tag-error.log >&2; exit 1; }
fi
cat > notes.md <<NOTES
Community VLC nightly build from upstream $sha.

Built with org.kde.Sdk//6.11 for org.kde.Platform//6.11.
See inputs.json for exact OSTree pins and build-*.json for provenance.
SHA256SUMS and sizes.json describe both native architecture payloads.
Recipe: $GITHUB_SERVER_URL/$GITHUB_REPOSITORY/tree/$GITHUB_SHA
Run: $GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID
NOTES
# This does not unlock publication: both existing authorization gates stay above.
python3 - <<'PYNOTES'
import json
from pathlib import Path
summary=json.loads(Path('verification-pair.json').read_text())
if summary['automated_status']=='WAIVED':
    with Path('notes.md').open('a') as notes:
        notes.write('\nKNOWN UPSTREAM ISSUE — automated verification WAIVED:\n')
        for issue in summary['known_issues']:
            notes.write(f"- {issue['architecture']}: X11 rapid OpenUri/Quit assertion crash; "
                        f"waiver {issue['id']}, expires {issue['expires_at']}; source {issue['source_commit']}.\n")
PYNOTES
diagnostic_assets=(verification-pair.json)
for log in xcb-gui-openuri-quit-rapid-*.log; do
  if [[ -f $log ]]; then diagnostic_assets+=("$log"); fi
done
gh release create "$version" --repo "$GITHUB_REPOSITORY" --target "$GITHUB_SHA" \
  --draft --prerelease --title "VLC $version" --notes-file notes.md \
  ./*.tar.zst SHA256SUMS sizes.json inputs.json build-x86_64.json build-aarch64.json \
  verification-x86_64.json verification-aarch64.json "${diagnostic_assets[@]}"
gh release edit "$version" --repo "$GITHUB_REPOSITORY" --draft=false
