#!/usr/bin/env bash
# deploy/render-test.sh: what deploy/render.sh must do, on a throwaway copy of deploy/ (it deletes directories, so never on this tree). No cluster.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
fails=0; bad() { echo "  FAIL $*"; fails=$((fails+1)); }; ok() { echo "  ok   $*"; }
# want <said when it holds> <said when it does not> <command...>
want() { local yes=$1 no=$2; shift 2; if "$@"; then ok "$yes"; else bad "$no"; fi; }
quiet() { "$@" >/dev/null 2>&1; }
D=$W/repo/deploy; mkdir -p "$D"; cp "$HERE/render.sh" "$D/"; cp -R "$HERE/manifests" "$D/"
GOOD=ghcr.io/ephico2real2/cmapi@sha256:$(printf 'a%.0s' {1..64})
INTERNAL=image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:$(printf 'b%.0s' {1..64})
R=$D/render.sh
PGOOD=ghcr.io/ephico2real2/cmapi-portal@sha256:$(printf 'e%.0s' {1..64})
PINTERNAL=image-registry.openshift-image-registry.svc:5000/cmapi/cmapi-portal@sha256:$(printf 'f%.0s' {1..64})
# r: render.sh with the front door's image, which every render needs; the cases about that image call "$R" themselves.
r() { "$R" "$@" --portal-image "$PGOOD"; }
# Fills exactly the placeholder: every other byte of every file is the source's.
r kind "$GOOD" "$W/o1" >/dev/null || bad "a digest was refused"
n=$(grep -rF "ghcr.io/ephico2real2/cmapi@sha256:DIGEST" "$D/manifests/components" "$D/manifests/environments/kind" | wc -l | tr -d ' ')
# Exactly four: two Deployments, each a migrate and a main container. One replaced by a pinned image would otherwise pass as
# "3 placeholders, 3 filled"; a Job or a sidecar on this image is a decision, and changes this number with it.
[ "$n" = 4 ] || bad "the source must hold the four cmapi image placeholders, got $n"
m=$(grep -rF "$GOOD" "$W/o1/components" "$W/o1/environment" | wc -l | tr -d ' ')
want "$n placeholders, $m filled" "$n placeholders, $m filled with the image" [ "$m" = "$n" ]
# Into a variable, not "| grep -q" in an if: under pipefail diff's own rc 1 made that pipeline false whatever it found.
extra=$(diff -r "$D/manifests/components" "$W/o1/components" | grep '^[<>]' | grep -vE 'image: |checksum/config: ')
if [ -n "$extra" ]; then bad "a line other than an image or the checksum changed: $extra"; else ok "only image and checksum lines changed"; fi
# And the same files: the line diff above cannot see a file the render dropped or added. The environment has no placeholder.
only=$(diff -r "$D/manifests/components" "$W/o1/components" | grep '^Only in')
if [ -n "$only" ]; then bad "the render's files are not the source's: $only"; else ok "the render holds every file of components, and no other"; fi
want "the environment is the source's, every byte" "the rendered environment differs" diff -r "$D/manifests/environments/kind" "$W/o1/environment"
want "IMAGE names it" "IMAGE does not name it" [ "$(cat "$W/o1/IMAGE")" = "$GOOD" ]
# The front door's image (#226): one placeholder, its own Deployment's, filled with --portal-image and with nothing else.
p=$(grep -rF "ghcr.io/ephico2real2/cmapi-portal@sha256:DIGEST" "$D/manifests/components" "$D/manifests/environments" | wc -l | tr -d ' ')
want "one cmapi-portal placeholder in the source" "the source holds $p cmapi-portal placeholders, not 1" [ "$p" = 1 ]
grep -qF "ghcr.io/ephico2real2/cmapi-portal@sha256:DIGEST" "$D/manifests/components/portal/10-front-door.yaml" || bad "the cmapi-portal placeholder is not the front door's"
want "the front door runs the portal image" "the front door does not run $PGOOD" grep -qxF "          image: $PGOOD" "$W/o1/components/portal/10-front-door.yaml"
m=$(grep -rF "$PGOOD" "$W/o1/components" "$W/o1/environment" | wc -l | tr -d ' ')
want "and nothing else does" "$m files name the portal image, not 1" [ "$m" = 1 ]
want "PORTAL_IMAGE names it" "PORTAL_IMAGE does not name it" [ "$(cat "$W/o1/PORTAL_IMAGE")" = "$PGOOD" ]
# Each image from its own repository: the API's image in the front door, or the front door's in the API, is refused.
if quiet "$R" kind "$GOOD" "$W/p1"; then bad "a render without --portal-image passed"; else ok "a render without --portal-image is refused"; fi
if quiet "$R" kind "$GOOD" --portal-image "$GOOD" "$W/p1"; then bad "the cmapi image was accepted as the front door's"; else ok "the cmapi image is refused as the front door's"; fi
if quiet r kind "$PGOOD" "$W/p1"; then bad "the cmapi-portal image was accepted as the API's"; else ok "the cmapi-portal image is refused as the API's"; fi
if quiet "$R" kind "$GOOD" --portal-image "ghcr.io/evil/cmapi-portal@sha256:$(printf 'c%.0s' {1..64})" "$W/p1"; then bad "another GHCR repository was accepted for the front door"; else ok "another GHCR repository is refused for the front door"; fi
if quiet "$R" kind "$GOOD" --portal-image "ghcr.io/ephico2real2/cmapi-portal@sha256:$(printf 'c%.0s' {1..63})" "$W/p1"; then bad "a short portal digest was accepted"; else ok "a short portal digest is refused"; fi
if quiet "$R" kind "$GOOD" --portal-image localhost/cmapi-portal:dev "$W/p1"; then bad "a portal tag was accepted without --allow-tag"; else ok "a portal tag is refused without --allow-tag"; fi
want "a portal tag with --allow-tag on kind" "a portal tag with --allow-tag refused on kind" quiet "$R" kind localhost/cmapi:dev --portal-image localhost/cmapi-portal:dev --allow-tag "$W/p2"
grep -q 'image: localhost/cmapi-portal:dev' "$W/p2/components/portal/10-front-door.yaml" || bad "--allow-tag did not fill the portal image"
if quiet "$R" crc "$INTERNAL" --portal-image localhost/cmapi-portal:dev --allow-tag "$W/p1"; then bad "a portal tag was accepted for crc"; else ok "a portal tag is refused for crc, --allow-tag or not"; fi
want "the internal registry's portal digest, and --portal-image=<ref>" "the internal registry's portal digest was refused" quiet "$R" crc "$INTERNAL" "--portal-image=$PINTERNAL" "$W/p3"
grep -qxF "          image: $PINTERNAL" "$W/p3/components/portal/10-front-door.yaml" || bad "--portal-image=<ref> did not fill the portal image"
if quiet "$R" kind "$GOOD" "$W/p1" --portal-image; then bad "--portal-image with no value passed"; else ok "--portal-image with no value is refused"; fi
if grep -rq 'sha256:DIGEST' "$W/o1"; then bad "a placeholder is left"; fi
# Refuses a tag without the flag, and leaves what was there.
r kind "$GOOD" "$W/o2" >/dev/null; echo keep >"$W/o2/keep"
if quiet r kind localhost/cmapi:dev "$W/o2"; then bad "a tag was accepted"; else want "a tag is refused and the last render stays" "the refusal deleted the last render" [ -e "$W/o2/keep" ]; fi
want "a tag with --allow-tag on kind" "--allow-tag refused on kind" quiet r kind localhost/cmapi:dev "$W/o3" --allow-tag
grep -q 'image: localhost/cmapi:dev' "$W/o3/components/cmapi/20-api.yaml" || bad "--allow-tag did not fill the image"
# --allow-tag means a kind test, never a deployment.
if r crc localhost/cmapi:dev "$W/o4" --allow-tag >/dev/null 2>&1; then bad "--allow-tag was accepted for crc"; else ok "--allow-tag is refused for anything but kind"; fi
# The internal registry's digest is what Wave 1 deploys, by digest; no flag that says "never a deployment".
want "the internal registry by digest" "the internal registry's digest needs --allow-tag" quiet r crc "$INTERNAL" "$W/o5"
# Exactly five on CRC: the four, and the realm sync's Job, which only environments/crc carries. Every one filled, and the checksum over CRC's own three files.
c=$(grep -r "sha256:DIGEST" "$D/manifests/environments/crc" | wc -l | tr -d ' ')
want "one placeholder in environments/crc" "environments/crc holds $c placeholders, not 1" [ "$c" = 1 ]
grep -q "sha256:DIGEST" "$D/manifests/environments/crc/realm/20-realm-sync.yaml" || bad "the placeholder is not the realm sync's"
m=$(grep -rF "$INTERNAL" "$W/o5/components" "$W/o5/environment" | wc -l | tr -d ' ')
want "five placeholders filled for crc" "$m filled for crc, not 5" [ "$m" = 5 ]
want "the realm import has no image of ours" "the realm import names the image" sh -c "! grep -q cmapi@ '$W/o5/environment/realm/10-realm-import.yaml'"
CK=$(grep -h 'checksum/config:' "$W/o5/components/cmapi/20-api.yaml" | sed -E 's/^ *checksum\/config: //')
for f in 10-env 20-config 30-trust; do
  cp "$D/manifests/environments/crc/$f.yaml" "$W/keep.yaml"; printf '# changed\n' >>"$D/manifests/environments/crc/$f.yaml"
  r crc "$INTERNAL" "$W/c5" >/dev/null; B=$(grep -h 'checksum/config:' "$W/c5/components/cmapi/20-api.yaml" | sed -E 's/^ *checksum\/config: //')
  want "a changed crc $f changes the checksum" "a changed crc $f did not change the checksum" [ "$B" != "$CK" ]
  cp "$W/keep.yaml" "$D/manifests/environments/crc/$f.yaml"
done
# A Route or a rule does not restart the pods, and the realm's files live outside what the checksum reads.
cp "$D/manifests/environments/crc/realm/10-realm-import.yaml" "$W/keep.yaml"; printf '# changed\n' >>"$D/manifests/environments/crc/realm/10-realm-import.yaml"
r crc "$INTERNAL" "$W/c5" >/dev/null; B=$(grep -h 'checksum/config:' "$W/c5/components/cmapi/20-api.yaml" | sed -E 's/^ *checksum\/config: //')
want "the realm import leaves the checksum" "the realm import changed the checksum" [ "$B" = "$CK" ]
cp "$W/keep.yaml" "$D/manifests/environments/crc/realm/10-realm-import.yaml"
if r crc "registry.example.com/x@sha256:$(printf 'c%.0s' {1..64})" "$W/o6" >/dev/null 2>&1; then bad "another registry was accepted"; else ok "another registry is refused"; fi
if r crc "ghcr.io/evil/cmapi@sha256:$(printf 'c%.0s' {1..64})" "$W/o6" >/dev/null 2>&1; then bad "another GHCR repository was accepted"; else ok "another GHCR repository is refused"; fi
if r crc "ghcr.io/ephico2real2/cmapi@sha256:$(printf 'c%.0s' {1..63})" "$W/o6" >/dev/null 2>&1; then bad "a short digest was accepted"; else ok "a short digest is refused"; fi
# The flag anywhere; the out dir is the out dir.
r kind localhost/cmapi:dev --allow-tag "$W/o7" >/dev/null 2>&1
want "--allow-tag before the out dir" "--allow-tag before the out dir: the out dir was ignored" [ -f "$W/o7/IMAGE" ]
# A partly written directory from an earlier run is replaced, leftovers and all.
r kind "$GOOD" "$W/o8" >/dev/null; printf 'image: ghcr.io/ephico2real2/cmapi@sha256:DIGEST\n' >"$W/o8/components/cmapi/99-leftover.yaml"; rm -f "$W/o8/IMAGE"
want "a partly written render is rendered again" "a partly written render was refused" quiet r kind "$GOOD" "$W/o8"
want "and its leftovers are gone" "a partly written render's leftover stayed" [ ! -e "$W/o8/components/cmapi/99-leftover.yaml" ]
# A placeholder the sed cannot fill fails, in any file.
printf 'image: ghcr.io/x@sha256:DIGEST\n' >"$D/manifests/components/cmapi/98-odd.yml"
if r kind "$GOOD" "$W/o9" >/dev/null 2>&1; then bad "a placeholder in a .yml passed"; else ok "a placeholder the render cannot fill fails"; fi
rm -f "$D/manifests/components/cmapi/98-odd.yml"
# checksum/config: the api's and the worker's pods restart when any of the three ConfigMaps changes, and nothing else does.
sums() { grep -h 'checksum/config:' "$1/components/cmapi/20-api.yaml" "$1/components/cmapi/30-worker.yaml" | sed -E 's/^ *checksum\/config: //'; }
psum() { grep -h 'checksum/config:' "$1/components/portal/10-front-door.yaml" | sed -E 's/^ *checksum\/config: //'; }
A0=$(sums "$W/o1"); n=$(printf '%s\n' "$A0" | sort -u | wc -l | tr -d ' ')
P0=$(psum "$W/o1")
printf '%s\n' "$P0" | grep -qxE '"[0-9a-f]{64}"' || bad "the front door's checksum is not one quoted SHA-256: $P0"
want "the front door's checksum is not the api's" "the front door carries the api's checksum" [ "$P0" != "$(printf '%s\n' "$A0" | head -1)" ]
want "both Deployments carry one value" "the Deployments' checksums differ: $A0" [ "$n" = 1 ]
[ "$(printf '%s\n' "$A0" | wc -l | tr -d ' ')" = 2 ] || bad "the checksum is not in both Deployments: $A0"
printf '%s\n' "$A0" | head -1 | grep -qE '^"[0-9a-f]{64}"$' || bad "the checksum is not a quoted SHA-256: $A0"
if grep -rq 'checksum/config\|CMAPI_CONFIG_CHECKSUM' "$W/o1/components/database-cnpg"; then bad "the checksum reached the database"; else ok "the database carries no checksum"; fi
r kind "$GOOD" "$W/s1" >/dev/null; want "two renders are identical" "two renders differ" diff -r "$W/o1" "$W/s1"
# Not the path: the same files in another checkout give the same value, or a change of directory would restart the pods.
mkdir -p "$W/elsewhere/deploy"; cp "$HERE/render.sh" "$W/elsewhere/deploy/"; cp -R "$D/manifests" "$W/elsewhere/deploy/"
"$W/elsewhere/deploy/render.sh" kind "$GOOD" --portal-image "$PGOOD" "$W/s2" >/dev/null; want "another checkout gives the same value" "the value depends on the path" [ "$(sums "$W/s2")" = "$A0" ]
# Pinned, so a change of method (and so a restart of every pod at the next deploy) is a decision, and macOS and Linux agree.
G=$D/manifests/environments/gold; mkdir -p "$G"; for c in env config trust portal-config; do printf 'metadata:\n  name: cmapi-%s\n' "$c" >"$G/$c.yaml"; done
r gold "$GOOD" "$W/s3" >/dev/null; want "the method is the one recorded" "the checksum method changed: $(sums "$W/s3" | head -1)" [ "$(sums "$W/s3" | head -1)" = '"dff6162fb72d31b5c1b3d66e83a5df01f57cff923f79db8ea8bc53277b14aa15"' ]
want "the front door's method is the same, over its one file" "the front door's checksum method changed: $(psum "$W/s3")" [ "$(psum "$W/s3")" = '"18576c5ced447caf1e9beff9222b56587216a68bfa70a2415ef3a61b700a1d69"' ]
rm -rf "$G"
for f in 10-env 20-config 30-trust; do
  cp "$D/manifests/environments/kind/$f.yaml" "$W/keep.yaml"; printf '# changed\n' >>"$D/manifests/environments/kind/$f.yaml"
  r kind "$GOOD" "$W/s4" >/dev/null; B=$(sums "$W/s4")
  [ "$(printf '%s\n' "$B" | sort -u | wc -l | tr -d ' ')" = 1 ] && [ "$(printf '%s\n' "$B" | wc -l | tr -d ' ')" = 2 ] || bad "after changing $f the Deployments disagree: $B"
  want "a changed $f changes it in both Deployments" "a changed $f did not change the checksum" [ "$B" != "$A0" ]
  want "and leaves the front door's" "a changed $f changed the front door's checksum" [ "$(psum "$W/s4")" = "$P0" ]
  cp "$W/keep.yaml" "$D/manifests/environments/kind/$f.yaml"
done
# The front door's checksum (#226): nginx reads its hosts once, at start, and config.json is mounted by subPath, which a changed
# ConfigMap never updates. So a changed cmapi-portal-config restarts the front door, and only the front door.
cp "$D/manifests/environments/kind/40-portal.yaml" "$W/keep.yaml"; printf '# changed\n' >>"$D/manifests/environments/kind/40-portal.yaml"
r kind "$GOOD" "$W/s4" >/dev/null
want "a changed cmapi-portal-config changes the front door's checksum" "a changed cmapi-portal-config did not change the front door's checksum" [ "$(psum "$W/s4")" != "$P0" ]
want "and leaves the api's and the worker's" "a changed cmapi-portal-config changed the api's or the worker's checksum" [ "$(sums "$W/s4")" = "$A0" ]
cp "$W/keep.yaml" "$D/manifests/environments/kind/40-portal.yaml"
cp "$D/manifests/environments/crc/60-portal.yaml" "$W/keep.yaml"; r crc "$INTERNAL" "$W/c6" >/dev/null; PC=$(psum "$W/c6")
printf '# changed\n' >>"$D/manifests/environments/crc/60-portal.yaml"; r crc "$INTERNAL" "$W/c6" >/dev/null
want "a changed crc 60-portal changes the front door's checksum" "a changed crc 60-portal did not change it" [ "$(psum "$W/c6")" != "$PC" ]
cp "$W/keep.yaml" "$D/manifests/environments/crc/60-portal.yaml"
# Moving bytes from one file's end to the next file's start changes it: the files are hashed one by one, not concatenated.
cp "$D/manifests/environments/kind/10-env.yaml" "$W/keep1.yaml"; cp "$D/manifests/environments/kind/20-config.yaml" "$W/keep2.yaml"
printf '# moved\n' >>"$D/manifests/environments/kind/10-env.yaml"; r kind "$GOOD" "$W/s5" >/dev/null; M1=$(sums "$W/s5")
cp "$W/keep1.yaml" "$D/manifests/environments/kind/10-env.yaml"; { printf '# moved\n'; cat "$W/keep2.yaml"; } >"$D/manifests/environments/kind/20-config.yaml"; r kind "$GOOD" "$W/s5" >/dev/null; M2=$(sums "$W/s5")
cp "$W/keep2.yaml" "$D/manifests/environments/kind/20-config.yaml"
want "bytes moved between two files change it" "bytes moved between two files did not change it" [ "$M1" != "$M2" ]
# An image change alone restarts through the image, not through this value.
r kind "ghcr.io/ephico2real2/cmapi@sha256:$(printf 'd%.0s' {1..64})" "$W/s6" >/dev/null; want "another image keeps the value" "another image changed the checksum" [ "$(sums "$W/s6")" = "$A0" ]
"$R" kind "$GOOD" --portal-image "ghcr.io/ephico2real2/cmapi-portal@sha256:$(printf 'd%.0s' {1..64})" "$W/s6" >/dev/null
both() { [ "$1" = "$2" ] && [ "$3" = "$4" ]; }
want "another portal image keeps both values" "another portal image changed a checksum" both "$(sums "$W/s6")" "$A0" "$(psum "$W/s6")" "$P0"
# A placeholder left fails the render, and a ConfigMap no file declares stops it before the last render is touched.
r kind "$GOOD" "$W/s7" >/dev/null; echo keep >"$W/s7/keep"
printf 'x: CMAPI_CONFIG_CHECKSUM\n' >"$D/manifests/components/cmapi/97-odd.yml"
if quiet r kind "$GOOD" "$W/s7"; then bad "a checksum placeholder in a .yml passed"; else ok "a checksum placeholder the render cannot fill fails"; fi
rm -f "$D/manifests/components/cmapi/97-odd.yml"
printf 'x: CMAPI_PORTAL_CONFIG_CHECKSUM\n' >"$D/manifests/components/portal/97-odd.yml"
if quiet r kind "$GOOD" "$W/s7"; then bad "a front door checksum placeholder in a .yml passed"; else ok "a front door checksum placeholder the render cannot fill fails"; fi
rm -f "$D/manifests/components/portal/97-odd.yml"
printf 'image: ghcr.io/ephico2real2/cmapi-portal@sha256:DIGEST\n' >"$D/manifests/components/portal/96-odd.yml"
if quiet r kind "$GOOD" "$W/s7"; then bad "a cmapi-portal placeholder in a .yml passed"; else ok "a cmapi-portal placeholder the render cannot fill fails"; fi
rm -f "$D/manifests/components/portal/96-odd.yml"
want "a failed render leaves the last good one" "a failed render replaced the last good one" [ -e "$W/s7/keep" ]
want "and its IMAGE" "a failed render removed IMAGE" [ -f "$W/s7/IMAGE" ]
want "and its PORTAL_IMAGE" "a failed render removed PORTAL_IMAGE" [ -f "$W/s7/PORTAL_IMAGE" ]
left=$(find "$W" -maxdepth 1 -name '.s7.*'); want "and nothing beside it" "a failed render left $left beside the out dir" [ -z "$left" ]
# The swap itself failing puts the last good render back.
REAL_MV=$(command -v mv); mkdir "$W/bin"
cat >"$W/bin/mv" <<STUB
#!/usr/bin/env bash
case "\$1" in */new) echo "mv: refused by the test" >&2; exit 1;; esac
exec "$REAL_MV" "\$@"
STUB
chmod +x "$W/bin/mv"
r kind "$GOOD" "$W/s9" >/dev/null; echo keep >"$W/s9/keep"
if PATH="$W/bin:$PATH" quiet r kind "$GOOD" "$W/s9"; then bad "a failed swap passed"; else want "a failed swap puts the last good render back" "a failed swap lost the last good render" [ -e "$W/s9/keep" ]; fi
# The out dir is what mkdir makes, not mktemp's 0700: a render other users or a container read must stay readable.
( umask 022; r kind "$GOOD" "$W/s10" >/dev/null ); m=$(stat -c '%a' "$W/s10" 2>/dev/null || stat -f '%Lp' "$W/s10")
want "the out dir has the umask's mode" "the out dir is mode $m, not 755" [ "$m" = 755 ]
# A trailing slash, and "link/": the link is what is replaced, and what it pointed at stays.
r kind "$GOOD" "$W/s11/" >/dev/null; r kind "$GOOD" "$W/s11/" >/dev/null; want "a trailing slash renders" "a trailing slash did not render" [ -f "$W/s11/IMAGE" ]
r kind "$GOOD" "$W/s12" >/dev/null; ln -s "$W/s12" "$W/s12link"
want "a link/ to a render renders" "a link/ to a render failed" quiet r kind "$GOOD" "$W/s12link/"
want "and what it pointed at stays" "a link/ deleted what it pointed at" [ -f "$W/s12/IMAGE" ]
for f in 10-env 20-config 30-trust 40-portal; do
  mv "$D/manifests/environments/kind/$f.yaml" "$W/keep.yaml"
  if quiet r kind "$GOOD" "$W/o2"; then bad "a render without $f passed"; else want "no $f stops the render and the last render stays" "the failure without $f deleted the last render" [ -e "$W/o2/keep" ]; fi
  mv "$W/keep.yaml" "$D/manifests/environments/kind/$f.yaml"
done
cp "$D/manifests/environments/kind/10-env.yaml" "$D/manifests/environments/kind/11-env-again.yaml"
if quiet r kind "$GOOD" "$W/s8"; then bad "two files declaring cmapi-env passed"; else ok "two files declaring one ConfigMap stop the render"; fi
rm -f "$D/manifests/environments/kind/11-env-again.yaml"
# It deletes only its own output: a directory it did not write is refused.
mkdir -p "$W/mine"; echo precious >"$W/mine/file"
if quiet r kind "$GOOD" "$W/mine"; then bad "render.sh replaced a directory it did not write"; else want "a directory it did not write is refused" "refused, and deleted it anyway" [ -e "$W/mine/file" ]; fi
r kind "$GOOD" "$D" >/dev/null 2>&1
want "deploy/ as the out dir does not delete deploy/" "deploy/ as the out dir deleted the manifests" [ -e "$D/manifests/README.md" ]
echo "render cases failed: $fails"; [ "$fails" = 0 ]
