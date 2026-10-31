#!/usr/bin/env bash
# Sourced by build.sh. Keep dependency build flags/toolchain overrides here;
# this file's digest is part of the dependency cache compatibility key.
build_contrib() {
  local SOURCE_DATE_EPOCH=$DEPS_SOURCE_DATE_EPOCH
  export SOURCE_DATE_EPOCH
  deps=/work/deps/$CACHE_KEY
  cache_hit=false
  [[ ! -f $deps/complete ]] || cache_hit=true
  export CC=gcc CXX=g++
  triplet=$(gcc -dumpmachine)
  mkdir -p "$deps/extras" /work/deps/tarballs
  if [[ ! -d $deps/contrib ]]; then
    cp -a /work/source/contrib "$deps/contrib"
    cp -a /work/source/extras/tools "$deps/extras/tools"
    # Upstream tracks only .gitignore in this directory. Source archives live
    # outside the compatibility tree; checksum/completion stamps do not.
    rm "$deps/contrib/tarballs/.gitignore"
    rmdir "$deps/contrib/tarballs"
    ln -s /work/deps/tarballs "$deps/contrib/tarballs"
  fi
  export PATH="$deps/extras/tools/build/bin:$PATH"
  if [[ $cache_hit == true ]]; then
    echo "Reusing completed contrib cache: $CACHE_KEY"
    return
  fi
  cd "$deps/extras/tools"
  if [[ ! -f Makefile ]]; then stage tools-bootstrap ./bootstrap; fi
  stage tools make -j"$jobs" all
  mkdir -p "$deps/contrib/linux"
  cd "$deps/contrib/linux"
  if [[ ! -f config.mak ]]; then
    stage contrib-bootstrap ../bootstrap --host="$triplet" --enable-sections --enable-libdsm --enable-dvdcss
  fi
  # Keep the target SDK's coherent desktop platform graph. In particular old
  # contrib GLib/X11 .pc files must not shadow Pango/Cairo's newer requirements.
  # Only packages actually detected by upstream as available in the SDK qualify.
  # Codecs, containers, networking and multimedia rendering libraries are not in
  # this allowlist: they and their remaining dependencies build from source.
  pkg-config --exists glib-2.0 gthread-2.0 gobject-2.0 libffi pangocairo
  local system_packages
  system_packages=$(make -s -f Makefile -f - print-sdk-packages <<'MAKE'
print-sdk-packages:
	@echo $(sort $(filter glib ffi fontconfig freetype2 harfbuzz fribidi libxml2 cairo pixman pango iconv gettext xproto xcb-proto xcb xau xorg-macros pthread-stubs wayland wayland-protocols wayland-scanner vulkan-headers vulkan-loader egl opengl,$(PKGS_FOUND)))
MAKE
  )
  printf 'SDK platform packages: %s\n' "$system_packages"
  stage contrib-list make "PKGS_FOUND=$system_packages" list
  stage contrib-fetch make -j"$jobs" "PKGS_FOUND=$system_packages" fetch
  stage contrib make -j"$jobs" "PKGS_FOUND=$system_packages"
  if find "$deps/contrib/$triplet" -name 'libQt6*' -print -quit | read -r _; then
    echo 'Unexpected contrib Qt library'; return 1
  fi
  touch "$deps/complete"
}
