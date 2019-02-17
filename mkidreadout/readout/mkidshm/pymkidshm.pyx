# Cython wrapper for libmkidshm
# Compile with: cython pymkidshm.pyx -o pymkidshm.c
#               gcc pymkidshm.c -fPIC -shared -I/home/neelay/anaconda2/envs/readout/include/python2.7/ -o pymkidshm.so -lmkidshm -lpthread -lrt

cimport numpy as np
import os

cdef extern from "<stdint.h>":
    ctypedef unsigned int uint32_t
    ctypedef unsigned long long uint64_t

cdef extern from "mkidshm.h":
    ctypedef struct MKID_IMAGE_METADATA:
        pass
    ctypedef struct MKID_IMAGE:
        pass
    ctypedef int image_t
    cdef int MKIDShmImage_open(MKID_IMAGE *imageStruct, char *imgName)
    cdef int MKIDShmImage_close(MKID_IMAGE *imageStruct)
    cdef int MKIDShmImage_create(MKID_IMAGE_METADATA *imageMetadata, char *imgName, MKID_IMAGE *outputImage)
    cdef int MKIDShmImage_populateMD(MKID_IMAGE_METADATA *imageMetadata, char *name, int nXPix, int nYPix, int useWvl, int nWvlBins, int wvlStart, int wvlStop)
    cdef int MKIDShmImage_startIntegration(MKID_IMAGE *image, uint64_t startTime, uint64_t integrationTime)
    cdef int MKIDShmImage_wait(MKID_IMAGE *image, int semInd)
    cdef int MKIDShmImage_checkIfDone(MKID_IMAGE *image, int semInd)



cdef class MKIDShmImage(object):
    cdef MKID_IMAGE image
    cdef int doneSemInd

    def __init__(self, name, doneSemInd=0, **kwargs):
        self.doneSemInd = doneSemInd
        if os.path.isfile(os.path.join('/dev/shm', name)):
            self.open(name)
            paramsMatch = True
            if kwargs.get('nXPix') is not None:
                paramsMatch &= (kwargs.get('nXPix') == self.image.nXPix)
            if kwargs.get('nYPix') is not None:
                paramsMatch &= (kwargs.get('nYPix') == self.image.nYPix)
            if kwargs.get('useWvl') is not None:
                paramsMatch &= (int(kwargs.get('useWvl')) == self.image.useWvl)
            if kwargs.get('nWvlBins') is not None:
                paramsMatch &= (kwargs.get('nWvlBins') == self.image.nWvlBins)
            if kwargs.get('wvlStart') is not None:
                paramsMatch &= (kwargs.get('wvlStart') == self.image.wvlStart)
            if kwargs.get('wvlStop') is not None:
                paramsMatch &= (kwargs.get('wvlStop') == self.image.wvlStop)
            if not paramsMatch:
                raise Exception('Image already exists, and provided parameters do not match.')

        else:
            self.create(name, kwargs.get('nXPix', 100), kwargs.get('nYPix', 100), kwargs.get('useWvl', False), 
                        kwargs.get('nWvlBins', 1), kwargs.get('wvlStart', 0), kwargs.get('wvlStop', 0))
            
         
    
    def create(self, name, nXPix, nYPix, useWvl, nWvlBins, wvlStart, wvlStop):
        cdef MKID_IMAGE_METADATA imagemd
        MKIDShmImage_populateMD(&imagemd, name.encode('UTF-8'), nXPix, nYPix, int(useWvl), nWvlBins, wvlStart, wvlStop)
        MKIDShmImage_create(&imagemd, name.encode('UTF-8'), &(self.image));

    def open(self, name):
        MKIDShmImage_open(&(self.image), name.encode('UTF-8'))

    def startIntegration(self, startTime=0, integrationTime=1):
        """
        Tells packetmaster to start an integration for this image
        Parameters
        ----------
            startTime: image start time (in seconds UTC?). If 0, start immediately w/
                timestamp that packetmaster is currently parsing.
            integrationTime: integration time in seconds(?)
        """
        MKIDShmImage_startIntegration(&(self.image), startTime, integrationTime)

    def receiveImage(self):
        """
        Waits for doneImage semaphore to be posted by packetmaster,
        then grabs the image from buffer
        """
        MKIDShmImage_wait(&(self.image), self.doneSemInd)
        return self._readImageBuffer()

    def _checkIfDone(self):
        """
        Non blocking. Returns True if image is done (doneImageSem is posted),
        False otherwise. Basically a wrapper for sem_trywait
        """
        return (MKIDShmImage_checkIfDone(&(self.image), self.doneSemInd) == 0)


    def _readImageBuffer(self):
        pass

    
