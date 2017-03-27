fixme:
- dep on athspectralscan + yanh
## Introduction

This is a simple, Python 3.5+ based ISM spectrum visualizer and dumper based on
the [ath9k spectral scan](https://wireless.wiki.kernel.org/en/users/drivers/ath9k/spectral_scan) feature and a monitor
interface that supports the [Radiotap header](http://www.radiotap.org/).

The core idea is to combine this sources to gain an unified view to the ISM spectrum. This allows a researcher not only
to inspect the regular WiFi traffic, but also look for the reasons for performance drops, often caused by
non-WiFi interferer.

This software is a pygame-based rewrite of Bob Copeland's [Speccy](https://github.com/bcopeland/speccy).

Currently the UI supports three views to inspect the samples in  "real time":

 * **Chanscan Mode**: The Hardware tunes to all WiFi channels and deliver a certain number of FFT samples per channel. Default is 8 samples.
 * **Background Mode**: The Hardware will deliver as much FFT samples as possible for one channel, but the sample stream will be interrupted e.g. by incoming WiFi packets. For performance reasons, not all FFT samples show up the in the UI.
 * **Heatmap Mode**: This mode merges WiFi samples (blue) with the FFT samples (green). Brighter color means higher power level. It shows power over time, so on both axis is time.
See below for the UI key bindings.

![Speccy-NG in Heatmap mode](doc/heatmap.gif "Speccy-NG in Heatmap mode")


Additional there are some offline analyser scripts in the `/analyzer` folder. For some teasers see [/doc folder](doc/) for example output.

## Prerequisites

 * Atheros based hardware that supports spectal scan. Look for "8Bit Spectral Scan" on the [Atheros page at Wikidevi](https://wikidevi.com/wiki/Atheros). If you want a cheap start, you can go for the [TL-WN722N](https://wikidevi.com/wiki/TP-LINK_TL-WN722N).
 * ath9k or ath9k_htc drivers compiled with debugfs enabled (this should be the default)
 * If you use the ath9k_htc driver, make sure that you use at least Firmware version 1.4, otherwise you will suffer on a bug that reports wrong TSF.
 * `git`, `iw`, `tshark`, `pip`
 * Python packages: `pcapy`. For the UI only: `pygame`

Some analyser scripts needs particular python packages, see the scripts for that.

## Installation on Ubuntu 14.04 / 16.04
    $ sudo apt-get install git iw tshark python-pip python-dev libpcap-dev
    $ sudo pip3 install pcapy pygame

To determine the firmware version if you use ath9k_htc based hardware:

    $ dmesg | grep "ath9k_htc: FW"
    [ 5967.965795] ath9k_htc 1-2:1.0: ath9k_htc: FW Version: 1.4

Grab the latest version of the code (or run `git pull` to update)

FIXME

Adjust default configuration file (parameter description see below). At least the user should adjust the sensor interface.

Finally start the application with:

    $ sudo python3 ui.py <interfacename>    