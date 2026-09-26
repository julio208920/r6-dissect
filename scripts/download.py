"""
download.py
===========
The "Get the Windows app" page: download link, install steps, updates, and
where Siege keeps its replays.
"""

from __future__ import annotations

import streamlit as st

import app_info
from app_info import (APP_NAME, APP_VERSION, HOW_IT_WORKS, NOTICE, RELEASES_URL, WINDOWS_INSTALLER, WINDOWS_ZIP,
                      is_windows_app, version_tuple)


@st.cache_data(ttl=600, show_spinner=False)
def latest_release() -> dict | None | str:
    """The newest Windows app release, None if there's none yet, or "unknown" if
    GitHub couldn't be reached (then the fixed /releases/latest links are used)."""
    try:
        return app_info.latest_release()
    except (OSError, ValueError):
        return "unknown"


release = latest_release()
installer_url = release["installer"] if isinstance(release, dict) else app_info.WINDOWS_DOWNLOAD_URL
zip_url = (release.get("zip") or app_info.WINDOWS_ZIP_URL) if isinstance(release, dict) else app_info.WINDOWS_ZIP_URL
notes_url = release["url"] if isinstance(release, dict) else RELEASES_URL

st.title("Get the Windows app")

if is_windows_app():
    st.success(f"You're using the Windows app, version {APP_VERSION}.", icon="✅")
    if isinstance(release, dict) and version_tuple(release["version"]) > version_tuple(APP_VERSION):
        st.info(f"Version {release['version']} is available.", icon="🆕")
        st.link_button(f"⬇ Download version {release['version']}", installer_url, type="primary")
        st.caption("Run the downloaded installer: it closes this app, updates it and keeps your shortcuts. "
                   f"[What's new]({notes_url})")
    elif isinstance(release, dict):
        st.caption("This is the newest version.")
    else:
        st.link_button("Check for a newer version", RELEASES_URL)
elif release is None:
    st.write(
        f"{APP_NAME} also runs as an app on your PC. It reads your Siege replays straight from the "
        "game's folder, so there's nothing to zip or upload, and your replays never leave your computer."
    )
    st.warning("The Windows app hasn't been published yet. Check back soon.", icon="⏳")
    st.link_button("See releases on GitHub", f"https://github.com/{app_info.GITHUB_REPO}/releases")
else:
    st.write(
        f"{APP_NAME} also runs as an app on your PC. It reads your Siege replays straight from the "
        "game's folder, so there's nothing to zip or upload, and your replays never leave your computer."
    )
    version = f"version {release['version']} · " if isinstance(release, dict) else ""
    st.link_button("⬇ Download for Windows", installer_url, type="primary")
    st.caption(f"{WINDOWS_INSTALLER} · {version}Windows 10 or 11 (64-bit) · about 65 MB · "
               f"[release notes]({notes_url})")

    st.subheader("Install")
    st.markdown(
        f"1. Download **{WINDOWS_INSTALLER}** above and open it.\n"
        "2. If Windows shows **Windows protected your PC**, click **More info**, then **Run anyway**. "
        "The app isn't code-signed yet, so Windows doesn't recognize it.\n"
        "3. Click through the installer. It doesn't need an administrator, and it adds "
        f"**{APP_NAME}** to the Start menu (and, if you like, the desktop).\n"
        f"4. Open **{APP_NAME}** from the Start menu. It opens in its own window and shows your latest match."
    )
    st.caption(f"To uninstall, go to **Settings > Apps > Installed apps**, find {APP_NAME}, and choose "
               f"**Uninstall**. Prefer no installer? Get the [portable zip]({zip_url}) ({WINDOWS_ZIP}): "
               "extract it and run **R6MatchStats.exe** from the R6MatchStats folder.")

    st.subheader("Check your download")
    st.markdown(
        "Only download the app from this page or its GitHub releases. To make sure your copy is the "
        "one that was published and wasn't changed on the way, compare its SHA-256 fingerprint with "
        "the published one. In PowerShell, in the folder you downloaded it to, run:"
    )
    st.code(f"Get-FileHash .\\{WINDOWS_INSTALLER}", language="powershell")
    sha256 = release.get("sha256") if isinstance(release, dict) else None
    if sha256:
        st.markdown("The **Hash** it prints should be exactly:")
        st.code(sha256.upper(), language=None)
    else:
        st.markdown(f"The **Hash** it prints should match the one for {WINDOWS_INSTALLER} in "
                    f"**{app_info.CHECKSUMS}** on the [release page]({notes_url}).")
    st.caption("Every time it opens, the app also checks that none of its own files were changed, added "
               "or removed since it was installed, and refuses to run if they were.")

st.subheader("Where are my replays?")
st.markdown(
    "Siege saves each match you play in a **MatchReplay** folder inside the game's install folder, "
    "one folder per match. The app finds it automatically for Steam and Ubisoft Connect installs. "
    "Otherwise, paste the path. The usual places are:\n"
    "- Steam: `C:\\Program Files (x86)\\Steam\\steamapps\\common\\Tom Clancy's Rainbow Six Siege\\MatchReplay`\n"
    "- Ubisoft Connect: `C:\\Program Files (x86)\\Ubisoft\\Ubisoft Game Launcher\\games\\"
    "Tom Clancy's Rainbow Six Siege\\MatchReplay`\n\n"
    "No replays there? Make sure **Match Replay** is turned on in the game's options, then play a match."
)

st.subheader("About this app")
st.markdown(
    f"{NOTICE}\n\n{HOW_IT_WORKS}\n\n"
    "**Your data:** the Windows app works on your PC, and the only thing it asks the internet for is "
    "whether GitHub has a newer version. On the website, uploaded replays are used only to build your "
    "report, and they're deleted once they've gone unused for an hour. Nothing is kept or shared."
)
