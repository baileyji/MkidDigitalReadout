import numpy as np
from mkidreadout.widesweep.WideSweepFile import WideSweepFile
from Resonator import Resonator
from matplotlib.backends.backend_pdf import PdfPages

import argparse
import os


class Autofit(object):
    def __init__(self, wideSweepFileName, reslocFileName, logFileName):
        self.logFile = open(logFileName, 'wb')
        self.wsf = WideSweepFile(wideSweepFileName)
        self.res = np.loadtxt(reslocFileName)
        self.n = self.res.shape[0]

    def run(self, nToDo='all', width=50, plotFileName=None):
        if plotFileName:
            pdf = PdfPages(plotFileName)
        else:
            pdf = None
        if nToDo == 'all': nToDo = self.n
        print nToDo
        for iToDo in range(nToDo):
            ind = self.res[iToDo, 1]
            print "begin iToDo=", iToDo, ' nToDo', nToDo, ' centered at ind=', ind, ' x=', self.wsf.x[ind]
            indStart = max(0, self.res[iToDo, 1] - width)
            indEnd = min(len(self.wsf.x), self.res[iToDo, 1] + width + 1 - 10)
            f = self.wsf.x[indStart:indEnd]
            I = self.wsf.I[indStart:indEnd]
            Ierr = self.wsf.Ierr[indStart:indEnd]
            # Ierr = self.wsf.Ierr
            Q = self.wsf.Q[indStart:indEnd]
            Qerr = self.wsf.Qerr[indStart:indEnd]
            # Qerr = self.wsf.Qerr
            res = Resonator(f, I, Ierr, Q, Qerr)
            rf = res.resfit()

            line = "%4i %17.6f %17.2f %17.2f %17.2f %17.2f\n" % (
            self.res[iToDo, 0], rf['f0'], rf['Q'], rf['Qi'], rf['Qc'], rf['chi2Mazin'])
            self.logFile.write(line)
            self.logFile.flush()
            print line
            res.plot(rf, pdf)
        if pdf:
            pdf.close()
        self.logFile.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Autofit peaks chosen in WideAna.py or WideAna.pro. "
                                                 "Writes results to wideSweepFileName-autofit.pdf and .log",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('wideSweepFile',
                        help='file generated by SegmentedSweep.vi')
    parser.add_argument('--reslocFile', default=None,
                        help='file generated by WideAna.py, defaults to '
                             'wideSweepFile with "good" appended to the name')
    if os.environ.has_key('MKID_DATA_DIR'):
        dataDirDefault = os.environ['MKID_DATA_DIR']
    else:
        dataDirDefault = '.'
    parser.add_argument('--dataDir', dest='dataDir', default=dataDirDefault,
                        help='location of data files')
    parser.add_argument('--nToDo', dest='nToDo', default='all',
                        help='number of resonators to fit')
    parser.add_argument('--width', dest='width', default=50,
                        help='number of data points around peak to use')

    args = parser.parse_args()
    print "args={}".format(args)
    dataDir = args.dataDir
    wideSweepFileName = os.path.join(args.dataDir, args.wideSweepFile)
    print "wsfn={}".format(wideSweepFileName)
    if args.reslocFile:
        reslocFileName = os.path.join(args.dataDir, args.reslocFile)
    else:
        s = os.path.splitext(args.wideSweepFile)
        reslocFileName = os.path.join(args.dataDir, s[0] + '-freqs-good' + s[1])
    print "rlfn={}".format(reslocFileName)
    plotFileName = os.path.splitext(wideSweepFileName)[0] + "-autofit.pdf"
    logFileName = os.path.splitext(wideSweepFileName)[0] + "-autofit.log"
    af = Autofit(wideSweepFileName, reslocFileName, logFileName)
    af.run(nToDo=args.nToDo, width=int(args.width), plotFileName=plotFileName)
