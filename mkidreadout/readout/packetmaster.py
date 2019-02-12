from mkidcore.config import yaml, yaml_object
import tempfile
import psutil
import subprocess
import select
import threading
import os
from mkidcore.corelog import getLogger

DEFAULT_CAPTURE_PORT = 50000  #This should be whatever is hardcoded in packetmaster -JB


@yaml_object(yaml)
class PacketMasterConfig(object):
    template = ('{ramdisk}\n'
                '{ncol:.0f} {nrow:.0f}\n'
                '{nuller:.0f}\n'
                '{nroach:.0f}\n'
                '{captureport:.0f}')

    def __init__(self, ramdisk='/mnt/ramdisk/', nrow=80, ncol=125, nuller=False, nroach=1, captureport=DEFAULT_CAPTURE_PORT):
        self.ramdisk = ramdisk
        self.nrows = nrow
        self.ncols = ncol
        self.nuller = nuller
        self.nroach = nroach
        self.captureport = captureport


class Packetmaster(object):
    # TODO overall log configuration must configure for a 'packetmaster' log
    def __init__(self, nroaches, nrows=100, ncols=100, shmImageList=[], ramdisk=None,
                 binary='', resume=False, captureport=DEFAULT_CAPTURE_PORT, start=True):
        self.ramdisk = ramdisk
        self.nroaches = nroaches
        if os.path.isfile(binary):
            self.binary_path = binary
        else:
            self.binary_path = os.path.join(os.path.dirname(__file__), 'packetmaster', 'packetmaster')
        self.nrows = nrows
        self.ncols = ncols
        self.captureport = captureport

        self.log = getLogger(__name__)
        self.plog = getLogger('packetmaster')

        self.log.debug('Using "{}" binary'.format(self.binary_path))

        packetmasters = [p.pid for p in psutil.process_iter(attrs=['pid','name'])
                         if 'packetmaster' in p.name()]
        if len(packetmasters)>1:
            self.log.critical('Multiple instances of packetmaster running. Aborting.')
            raise RuntimeError('Multiple instances of packetmaster')

        self._process = psutil.Process(packetmasters[0]) if packetmasters else None

        if self._process is not None:
            if resume:
                try:
                    connections = [x for x in self._process.get_connections()
                                   if x.status == psutil.CONN_LISTEN]
                    self.captureport = connections[0].laddr.port
                except Exception:
                    self.log.debug('Unable to determine listening port: ', exc_info=True)

                self.log.warning('Reusing existing packetmaster instance, logging will not work')
            else:
                self.log.warning('Killing existing packetmaster instance.')
                self._process.kill()
                self._process = None

        self._pmmonitorthread = None

        if start:
            self._start()

    @property
    def is_running(self):
        #TODO note this returns true even if _process.status() == psutil.STATUS_ZOMBIE
        try:
            return self._process.is_running()
        except AttributeError:
            return False

    def _monitor(self):

        def doselect(timeout=1):
            readable, _, _ = select.select([self._process.stdout, self._process.stderr], [],
                                           [self._process.stdout, self._process.stderr], timeout)
            for r in readable:
                try:
                    l = r.readline().strip()
                    if not l:
                        continue
                    if r == self._process.stdout:
                        self.plog.info(l)
                    else:
                        self.plog.error(l)
                except:
                    self.log.debug('Caught in monitor: ', exc_info=True)

        while True:
            if not self.is_running:
                self.log.info('Ending monitor thread, packetmaster no longer running')
                break
            doselect()
        doselect(0)

    def _start(self):
        if self.is_running:
            return

        self.log.info('Starting packetmaster...')

        self._cleanup()

        with tempfile.NamedTemporaryFile('w', suffix='.cfg', delete=False) as tfile:
            s = PacketMasterConfig.template.format(ramdisk=self.ramdisk, nrow=self.nrows,
                                                   ncol=self.ncols, nuller=self.nuller,
                                                   nroach=self.nroaches, captureport=self.captureport)
            tfile.write(s)

        self._process = psutil.Popen((self.binary_path, tfile.name), stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,
                                     shell=False, cwd=None, env=None, creationflags=0)
        code = self._process.poll()
        if code is None:
            self.log.info('started. Starting monitor.')
            self._pmmonitorthread = threading.Thread(target=self._monitor, name='Packetmaster IO Handler')
            self._pmmonitorthread.daemon = True
            self._pmmonitorthread.start()
        else:
            self.log.info('started. terminated with return code {}'.format(code))

    def _cleanup(self):
        try:
            if os.path.exists(os.path.join(self.ramdisk, 'QUIT')):
                os.remove(os.path.join(self.ramdisk, 'QUIT'))
            if os.path.exists(os.path.join(self.ramdisk, 'START')):
                os.remove(os.path.join(self.ramdisk, 'START'))
            if os.path.exists(os.path.join(self.ramdisk, 'STOP')):
                os.remove(os.path.join(self.ramdisk, 'STOP'))
        except Exception:
            getLogger(__name__).warning('Unable to cleanup control files',exc_info=True)

    def startobs(self, datadir):
        sfile = os.path.join(self.ramdisk, 'START_tmp')
        self.log.debug("Starting packet save. Start file loc: %s", sfile[:-4])
        with open(sfile, 'w') as f:
            f.write(datadir)
        os.rename(sfile, sfile[:-4])  # prevent race condition

    def stopobs(self):
        self.log.debug("Stopping packet save.")
        open(os.path.join(self.ramdisk, 'STOP'), 'w').close()

    def quit(self):
        open(os.path.join(self.ramdisk, 'QUIT'), 'w').close()   # tell packetmaster to end
