import numpy as np
import tensorflow as tf
import os, sys, glob
import argparse
import logging
import matplotlib.pyplot as plt
import skimage.feature as skf
import mkidreadout.configuration.sweepdata as sd
import mkidreadout.configuration.powersweep.ml.tools as mlt
from mkidcore.corelog import getLogger
from mkidreadout.configuration.powersweep.ml.wpsnn import N_CLASSES
import mkidcore.instruments as inst

N_RES_PER_BOARD = 1024

def makeWPSMap(modelDir, freqSweep, freqStep=None, attenClip=5):
    mlDict, sess, graph, x_input, y_output, keep_prob, is_training = mlt.get_ml_model(modelDir)
    
    if freqStep is None:
        freqStep = freqSweep.freqStep

    attens = freqSweep.atten[attenClip:-attenClip]
    freqStart = freqSweep.freqs[0, 0] + freqSweep.freqStep*mlDict['freqWinSize']
    freqEnd = freqSweep.freqs[-1, -1] - freqSweep.freqStep*mlDict['freqWinSize']
    freqs = np.arange(freqStart, freqEnd, freqStep)

    wpsImage = np.zeros((len(attens), len(freqs), N_CLASSES))
    nColors = 2
    if mlDict['useIQV']:
        nColors += 1
    if mlDict['useVectIQV']:
        nColors += 2

    chunkSize = 2500
    imageList = np.zeros((chunkSize, mlDict['attenWinBelow'] + mlDict['attenWinAbove'] + 1, mlDict['freqWinSize'], nColors))
    labelsList = np.zeros((chunkSize, N_CLASSES))

    for attenInd in range(len(attens)):
        for chunkInd in range(len(freqs)/chunkSize + 1):
            nFreqsInChunk = min(chunkSize, len(freqs) - chunkSize*chunkInd)
            for i, freqInd in enumerate(range(chunkSize*chunkInd, chunkSize*chunkInd + nFreqsInChunk)):
                imageList[i], _, _  = mlt.makeWPSImage(freqSweep, freqs[freqInd], attens[attenInd], mlDict['freqWinSize'],
                        1+mlDict['attenWinBelow']+mlDict['attenWinAbove'], mlDict['useIQV'], mlDict['useVectIQV']) 
            wpsImage[attenInd, chunkSize*chunkInd:chunkSize*chunkInd + nFreqsInChunk] = sess.run(y_output, feed_dict={x_input: imageList[:nFreqsInChunk], keep_prob: 1, is_training: False})
            print 'finished chunk', chunkInd, 'out of', len(freqs)/chunkSize

        print 'atten:', attens[attenInd]


    return wpsImage, freqs, attens

def findResonators(wpsmap, freqs, attens, peakThresh=0.5, minPeakDist=5):
    resCoords = skf.peak_local_max(wpsmap[:,:,0], min_distance=minPeakDist, threshold_abs=peakThresh, exclude_border=False)
    resFreqs = freqs[resCoords[:,1]]
    resAttens = attens[resCoords[:,0]]

    scores = np.zeros(len(resFreqs))
    for i in range(len(resFreqs)):
        scores[i] = wpsmap[resCoords[i,0], resCoords[i,1], 0]

    sortedInds = np.argsort(resFreqs)
    resFreqs = resFreqs[sortedInds]
    resAttens = resAttens[sortedInds]
    scores = scores[sortedInds]

    return resFreqs, resAttens, scores

def saveMetadata(outFile, resFreqs, resAttens, scores, feedline, band, collThresh=200.e3):
    assert len(resFreqs) == len(resAttens) == len(scores), 'Lists must be the same length'

    flag = np.zeros(len(resFreqs))
    collMask = np.abs(np.diff(resFreqs)) < collThresh
    collMask = np.append(collMask, False)
    flag[collMask] = sd.ISBAD
    flag[~collMask] = sd.ISGOOD
    
    badScores = np.zeros(len(scores))

    resIDStart = feedline*10000
    if band.lower() == 'b':
        resIDStart += N_RES_PER_BOARD
    resIDs = np.arange(resIDStart, resIDStart + len(resFreqs))

    md = sd.SweepMetadata(resIDs, wsfreq=resFreqs, mlfreq=resFreqs, mlatten=resAttens, ml_isgood_score=scores, 
            ml_isbad_score=badScores, flag=flag)
    md.save(outFile)
    

if __name__=='__main__':
    parser = argparse.ArgumentParser(description='WPS ML Inference Script')
    parser.add_argument('model', help='Directory containing ML model')
    parser.add_argument('inferenceData', help='npz file containing WPS data')
    parser.add_argument('-o', '--metadata', default=None, help='Output metadata file')
    parser.add_argument('-s', '--save-wpsmap', action='store_true', help='Save npz file containing raw ML convolution output')
    parser.add_argument('-r', '--remake-wpsmap', action='store_true', help='Regenerate wps map file')
    args = parser.parse_args()

    if args.metadata is None:
        args.metadata = os.path.join(os.path.dirname(args.inferenceData), os.path.basename(args.inferenceData).split('.')[0] + '_metadata.txt')

    elif not os.path.isabs(args.metadata):
        args.metadata = os.path.join(os.path.dirname(args.inferenceData), args.metadata)

    wpsmapFile = os.path.join(os.path.dirname(args.inferenceData), os.path.basename(args.inferenceData).split('.')[0] \
            + '_' + os.path.basename(args.model) + '.npz')

    if not os.path.isfile(wpsmapFile) or args.remake_wpsmap:
        print 'Generating new WPS map'
        freqSweep = sd.FreqSweep(args.inferenceData)
        wpsmap, freqs, attens = makeWPSMap(args.model, freqSweep)

        if args.save_wpsmap:
            np.savez(wpsmapFile, wpsmap=wpsmap, freqs=freqs, attens=attens)

    else:
        print 'Loading WPS map', wpsmapFile
        f = np.load(wpsmapFile)
        wpsmap = f['wpsmap']
        freqs = f['freqs']
        attens = f['attens']

    resFreqs, resAttens, scores = findResonators(wpsmap, freqs, attens)

    if resFreqs[0] < 4.7e9:
        band = 'a'
    else:
        band = 'b'

    print 'Saving resonator metadata in:', args.metadata
    saveMetadata(args.metadata, resFreqs, resAttens, scores, inst.guessFeedline(os.path.basename(args.inferenceData)), band)
