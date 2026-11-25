# Frame Editor
Edit video in a browser or the Electron desktop app. Frame Editor includes a timeline, trimming, markers, and audio controls. Rendering requires FilmCraft, which is installed separately.

## What is included
- Timeline/preview interface, markers, linked edits, trim/cut, stills and audio controls
- Local desktop file import, project persistence and render adapters
- Narrow sandboxed Electron IPC and authenticated remote-work protocols
- Signed-update implementation, disabled unless you supply your own public verification key
- Optional AI/provider interfaces with caller-supplied instructions

## Layout
web/ contains the HTTP worker, UI and optional authenticated front/object-storage adapters.
desktop/ contains the Electron shell and its local Python runtime.

This is a clean source edition, not the original hosted service or an installer release. No account configuration, projects, media, private prompts, release-signing identity, cloud credentials, engine binaries or model weights are included.

## Dependencies and development
Python 3.12+, Node.js 22+, FFmpeg/ffprobe, NumPy, Pillow, requests, cryptography and optionally boto3. FilmCraft v0.20.1 must be obtained separately from https://github.com/storytold/filmcraft and remains subject to its own licence.

~~~sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cd desktop
npm ci --ignore-scripts
~~~
For a desktop development launch configure FRAME_DEV_PYTHON, FRAME_DEV_ENGINE and FRAME_DEV_VENDOR for your own local runtimes, then npm start. The optional prepare_vendor.py build helper downloads substantial pinned third-party packages; inspect it and plan space before invoking it. No vendor binaries are checked in.

Remote services are optional and default to the non-working example.invalid origin. Supply your own HTTPS FRAME_REMOTE_ORIGIN and compatible authenticated backend; this repository grants no access to the original service. FRAME_UPDATE_PUBLIC_KEY points to your own update verification key.

AI workflows require PUBLIC_PROMPTS_FILE with your own nonempty instructions; see prompts.example.json for the keys. There is no fallback to private instructions.

## Checks and limits
~~~sh
python -B -m unittest discover -s tests -v
cd desktop
npm run check
~~~
The public edition is verified separately from the historical private product. Source checks and a Linux worker smoke do not establish native Windows/macOS installation, Gatekeeper/notarization, provider access or production readiness. Large-object/cloud and PC media workflows require independently configured external workers.

Source-inspection licence: see LICENSE. FilmCraft, Electron, FFmpeg, Python and other dependencies retain their own licences. Original application integration developed with AI assistance.

## Continuous integration
A reference GitHub Actions workflow is included at ci/github-actions.yml. To activate it in your own repository, place it under .github/workflows/. Its presence as a reference does not mean hosted CI is enabled or has passed.
