# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# WRF-ARW v4.6.1 + WPS v4.6.0 — Mt Washington wave pipeline image.
#
# Build (native arm64):  docker build --platform linux/arm64 -t mtw-wrf:4.6.1 .
#
# Pins (SHA-256 verified below; recorded in wrf/README.md):
#   ubuntu:24.04            digest 534baea6…530eb55 (multi-arch index)
#   WRF v4.6.1              b8ec11b2…c50b5f2
#   WPS v4.6.0 tag archive  ca7bbfc6…eb9a309b
#   Jasper 2.0.33           28d28290…a611801a
#   micromamba 2.9.0        9f93b974…b74cb7a7
#   convert_geotiff         commit da7003fe… (cloned into the build context)
#
# The same Dockerfile builds linux/amd64 (no emulation is used on this box).
# ---------------------------------------------------------------------------
FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55

# pipefail matters for the compile steps below
SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND=noninteractive TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget git make m4 bc bzip2 file time \
      gcc g++ gfortran \
      csh perl \
      openmpi-bin libopenmpi-dev \
      zlib1g-dev libpng-dev libgeotiff-dev libtiff-dev \
      libhdf5-dev libnetcdf-dev libnetcdff-dev netcdf-bin \
      cmake \
      python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

# --------------------------------------------------------------- Jasper 2.0.33
# Ubuntu 24.04 no longer ships libjasper-dev; WPS's GRIB2 support needs it
# (the WPS configure reads JASPERLIB / JASPERINC).
COPY src/jasper-2.0.33.tar.gz /tmp/jasper-2.0.33.tar.gz
RUN echo "28d28290cc2eaf70c8756d391ed8bcc8ab809a895b9a67ea6e89da23a611801a  /tmp/jasper-2.0.33.tar.gz" | sha256sum -c - \
 && cd /opt && tar xzf /tmp/jasper-2.0.33.tar.gz && rm /tmp/jasper-2.0.33.tar.gz \
 && cmake -S /opt/jasper-2.0.33 -B /opt/jasper-build \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/jasper \
      -DJAS_ENABLE_DOC=OFF -DJAS_ENABLE_PROGRAMS=OFF \
 && cmake --build /opt/jasper-build -j 8 \
 && cmake --install /opt/jasper-build

ENV JASPERLIB=/opt/jasper/lib JASPERINC=/opt/jasper/include
ENV LD_LIBRARY_PATH=/opt/jasper/lib

# ------------------------------------------------------------------ WRF v4.6.1
COPY src/WRF-4.6.1.tar.gz /tmp/WRF-4.6.1.tar.gz
RUN echo "b8ec11b240a3cf1274b2bd609700191c6ec84628e4c991d3ab562ce9dc50b5f2  /tmp/WRF-4.6.1.tar.gz" | sha256sum -c - \
 && tar xzf /tmp/WRF-4.6.1.tar.gz -C /opt \
 && mv /opt/WRFV4.6.1 /opt/WRF \
 && rm /tmp/WRF-4.6.1.tar.gz

# The WRF configure menu is filtered by `uname -m`, so the GNU dmpar entry has
# a different number per arch — read off WRF's own menus: 7 on aarch64
# ("Linux armv7l aarch64, gnu OpenMPI"), 34 on x86_64 ("Linux x86_64, gnu
# compiler (dmpar)"). Nesting = 1 (basic). GNU 13 on arm64 needs
# -fallow-argument-mismatch and -fallow-invalid-boz appended to the Fortran
# base options (unused on x86_64, harmless there).
RUN set -o pipefail \
 && cd /opt/WRF && export NETCDF=/usr \
 && case "$(uname -m)" in \
      aarch64) WRF_CONFIG=7 ;; \
      x86_64)  WRF_CONFIG=34 ;; \
      *) echo "unsupported build arch: $(uname -m)" >&2; exit 1 ;; \
    esac \
 && printf '%s\n1\n' "$WRF_CONFIG" | timeout 180 ./configure \
 && sed -i 's/^\(FCBASEOPTS_NO_G[[:space:]]*=.*\)$/\1 -fallow-argument-mismatch -fallow-invalid-boz/' configure.wrf \
 && grep -n "fallow-argument-mismatch" configure.wrf \
 && ./compile -j 8 em_real 2>&1 | tee /opt/WRF/compile.log | tail -40 \
 && test -s main/wrf.exe && test -s main/real.exe && test -s main/ndown.exe \
 && ls -l main/wrf.exe main/real.exe main/ndown.exe

# ------------------------------------------------------------------ WPS v4.6.0
COPY src/WPS-4.6.0.tar.gz /tmp/WPS-4.6.0.tar.gz
RUN echo "ca7bbfc6c28a107c6eb00ded70e693f5c9a3926ecde7656f49e306c9eb9a309b  /tmp/WPS-4.6.0.tar.gz" | sha256sum -c - \
 && tar xzf /tmp/WPS-4.6.0.tar.gz -C /opt \
 && mv /opt/WPS-4.6.0 /opt/WPS \
 && rm /tmp/WPS-4.6.0.tar.gz

# WPS 4.6.0 ships no aarch64 entry; its x86_64 gfortran entry carries no
# x86-only flags, so the ARCH line is patched to also match aarch64.
# Serial + GRIB2 = menu option 1. `./compile wps` builds exactly
# geogrid+ungrib+metgrid; the util targets (int2nc et al.) are not part of
# this pipeline and are not built.
RUN set -o pipefail \
 && cd /opt/WPS \
 && sed -i 's|^#ARCH    Linux x86_64, gfortran|#ARCH    Linux x86_64 aarch64, gfortran|' arch/configure.defaults \
 && export NETCDF=/usr JASPERLIB=/opt/jasper/lib JASPERINC=/opt/jasper/include WRF_DIR=/opt/WRF \
 && printf '1\n' | timeout 180 ./configure \
 && sed -i 's/^FFLAGS\([[:space:]]*\)=\(.*\)$/FFLAGS\1=\2 -fallow-argument-mismatch/' configure.wps \
 && sed -i 's/^F77FLAGS\([[:space:]]*\)=\(.*\)$/F77FLAGS\1=\2 -fallow-argument-mismatch/' configure.wps \
 && sed -i 's/-lnetcdf$/-lnetcdf -lnetcdff/' configure.wps \
 && grep -n "lnetcdf" configure.wps \
 && ./compile wps 2>&1 | tee /opt/WPS/compile.log | tail -30 \
 && test -s geogrid/src/geogrid.exe && test -s ungrib/src/ungrib.exe && test -s metgrid/src/metgrid.exe \
 && ls -l geogrid/src/geogrid.exe ungrib/src/ungrib.exe metgrid/src/metgrid.exe

# -------------------------------------------------- convert_geotiff (pinned)
COPY src/convert_geotiff /opt/convert_geotiff
# The 2014-era generated build files look stale to a fresh clone (make wants
# aclocal-1.14 to regenerate aclocal.m4); pin their timestamps instead of
# installing a decade-old automake.
RUN cd /opt/convert_geotiff \
 && touch -d "2020-01-01" configure.ac Makefile.am \
 && touch -d "2021-01-01" aclocal.m4 configure Makefile.in config.h.in \
 && ./configure \
 && make -j 8 \
 && test -x convert_geotiff

# ------------------------------------ Python 3.12 layer (conda-forge binaries)
# wrf-python has no pip sdist that builds on Python 3.12; conda-forge ships
# platform binaries (1.4.2 — same API: destagger, to_np, interplevel). The
# micromamba 2.9.0 binary in src/ matches the build host — aarch64 on the
# MacBook, x86_64 on a Linux server (same release asset, renamed); this picks
# whichever is present. Everything else is the same pinned stack.
COPY src/micromamba-2.9.0-linux-* /tmp/micromamba/
RUN MAMBA_ARCH=$( [ "$(uname -m)" = "aarch64" ] && echo aarch64 || echo x86_64 ) \
 && mv "/tmp/micromamba/micromamba-2.9.0-linux-${MAMBA_ARCH}" /usr/local/bin/micromamba \
 && rm -rf /tmp/micromamba \
 && chmod +x /usr/local/bin/micromamba && /usr/local/bin/micromamba --version \
 && MAMBA_ROOT_PREFIX=/opt/mamba /usr/local/bin/micromamba create -y -p /opt/venv \
      -c conda-forge --channel-priority strict \
      "python=3.12" "wrf-python=1.4.2" xarray netCDF4 scipy matplotlib rasterio boto3 herbie-data 2>&1 | tail -12 \
 && /opt/venv/bin/python -c "import wrf, herbie, xarray, netCDF4, rasterio, scipy, matplotlib, boto3; print('python layer OK — wrf-python', wrf.__version__)" \
 && MAMBA_ROOT_PREFIX=/opt/mamba /usr/local/bin/micromamba list -p /opt/venv --explicit > /opt/venv/conda-explicit.txt \
 && MAMBA_ROOT_PREFIX=/opt/mamba /usr/local/bin/micromamba clean -a -y

ENV PATH=/opt/venv/bin:/opt/convert_geotiff:/opt/WRF/main:/opt/WPS/geogrid/src:/opt/WPS/ungrib/src:/opt/WPS/metgrid/src:$PATH
ENV MPLBACKEND=Agg
ENV OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1

WORKDIR /wrf
