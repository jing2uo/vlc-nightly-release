FROM localhost/vlc-nightly-builder
# Test tools stay in an isolated rootless container, never on Fedora.
# The base Flatpak package pulls PipeWire's replacement daemon. Only this
# disposable test image swaps it for a private, easily inspected Pulse server.
RUN dnf -y swap --allowerasing pipewire-pulseaudio pulseaudio \
    && dnf -y install --setopt=install_weak_deps=False dbus-daemon xorg-x11-server-Xvfb \
    xwininfo xprop xwd xdotool pulseaudio pulseaudio-utils ImageMagick curl gdb \
    && dnf clean all
ENTRYPOINT ["/bin/bash"]
