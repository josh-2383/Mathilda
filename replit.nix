{pkgs}: {
  deps = [
    pkgs.nano
    pkgs.glibcLocales
    pkgs.cacert
    pkgs.pkg-config
    pkgs.libffi
    pkgs.zlib
    pkgs.tk
    pkgs.tcl
    pkgs.openjpeg
    pkgs.libwebp
    pkgs.libtiff
    pkgs.libjpeg
    pkgs.libimagequant
    pkgs.lcms2
    pkgs.freetype
    pkgs.libxcrypt
    pkgs.mercurial
    pkgs.unzip
    pkgs.wget
    pkgs.python311Full
    pkgs.python311Packages.pip
    pkgs.tesseract
  ];
}
