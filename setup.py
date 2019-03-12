from __future__ import print_function
import setuptools, sys, numpy
import os
from setuptools.command.install import install
from setuptools.command.develop import develop
import subprocess
import platform
from setuptools.extension import Extension
from Cython.Build import cythonize

#pip install -e git+http://github.com/mazinlab/mkidreadout.git@restructure#egg=mkidreadout --src ./mkidtest


def get_virtualenv_path():
    """Used to work out path to install compiled binaries to."""
    if hasattr(sys, 'real_prefix'):
        return sys.prefix

    if hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix:
        return sys.prefix

    if 'conda' in sys.prefix:
        return sys.prefix

    return None


def compile_and_install_software():
    """Used the subprocess module to compile/install the C software."""
    
    #don't compile if installing on anything that's not linux
    if platform.system()!='Linux':
        return

    src_path = './mkidreadout/readout/packetmaster/'

    # compile the software
    cmds = ["gcc -Wall -Wextra -o packetmaster packetmaster.c -I. -lm -lrt -lpthread -O3"]
#            'gcc -o Bin2PNG Bin2PNG.c -I. -lm -lrt -lpng',
#            'gcc -o BinToImg BinToImg.c -I. -lm -lrt',
#            'gcc -o BinCheck BinCheck.c -I. -lm -lrt']
    venv = get_virtualenv_path()

    try:

        for cmd in cmds:
            if venv:
                cmd += ' --prefix=' + os.path.abspath(venv)
            subprocess.check_call(cmd, cwd=src_path, shell=True)
    except Exception as e:
        print(str(e))
        raise e


class CustomInstall(install, object):
    """Custom handler for the 'install' command."""
    def run(self):
        compile_and_install_software()
        super(CustomInstall,self).run()


class CustomDevelop(develop, object):
    """Custom handler for the 'install' command."""
    def run(self):
        compile_and_install_software()
        super(CustomDevelop,self).run()


roach2utils_ext = Extension(name="mkidreadout.channelizer.roach2utils",
                       sources=['mkidreadout/channelizer/roach2utils.pyx'],
                       include_dirs=[numpy.get_include()],
                       extra_compile_args=['-fopenmp'],
                       extra_link_args=['-fopenmp'])

pymkidshm_ext = Extension(name="mkidreadout.readout.mkidshm.pymkidshm",
                        sources=['mkidreadout/readout/mkidshm/pymkidshm.pyx'],
                        include_dirs=[numpy.get_include()],
                        extra_compile_args=['-shared', 'fPIC'],
                        extra_link_args=['-lmkidshm', '-lrt', '-lptrhead'])

with open("README.md", "r") as fh:
    long_description = fh.read()


setuptools.setup(
    name="mkidreadout",
    version="0.0.1",
    author="MazinLab",
    author_email="mazinlab@ucsb.edu",
    description="An UVOIR MKID Data Readout Package",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/MazinLab/MKIDReadout",
    packages=setuptools.find_packages(),
    package_data={'mkidreadout': ('config/*.yml', 'resources/firmware/*', 'resources/firfilters/*')},
    scripts=['mkidreadout/channelizer/initgui.py',
             'mkidreadout/channelizer/hightemplar.py',
             'mkidreadout/readout/dashboard.py',
             'mkidreadout/configuration/powersweep/clickthrough_hell.py'],
    ext_modules=cythonize([roach2utils_ext, pymkidshm_ext]), 
    classifiers=(
        "Programming Language :: Python :: 2.7",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX",
        "Development Status :: 1 - Planning",
        "Intended Audience :: Science/Research"
    ),
    cmdclass={'install': CustomInstall,'develop': CustomDevelop}
)



