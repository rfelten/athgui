#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#   This file is part of the athgui project.
#
#   Copyright (C) 2017 Robert Felten - https://github.com/rfelten/
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software Foundation,
#   Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA

import sys
import math
import pygame
import logging
import multiprocessing as mp
import queue
from athspectralscan import AthSpectralScanner, AthSpectralScanDecoder, DataHub
from yanh.airtime import AirtimeCalculator
logger = logging.getLogger(__name__)
logger.level = logging.DEBUG
logger.addHandler(logging.StreamHandler(sys.stdout))


class SimpleUI(object):

    (view_unknown, view_cs, view_bg, view_hm) = range(-1, 3)

    def __init__(self, athscanner, ath_queue_in, airtime_queue_in):
        pygame.init()
        pygame.mouse.set_visible(1)
        pygame.key.set_repeat(20, 100)  # wait 20ms, then event every 100ms
        self.clock = pygame.time.Clock()
        self.caption_prefix = "Ath GUI"
        self.height = 600
        #self.width = 800
        self.tu_per_px = 225  # default: 115 for 8/2/16/0
        #self.width = (100 * 1000) // (self.tu_per_px-3) -2 # try to align for beacons
        self.width = (1024 * 100) // self.tu_per_px   # try to align for beacons
        self.screen = pygame.display.set_mode((self.width, self.height))
        self.bg_color = (0, 0, 0)
        self.line_color = (30, 30, 30)
        self.text_color = (0, 150, 50)
        self.screen.fill(self.bg_color)

        self.running = True
        self.flush_data = False
        self.clean_screen = False

        self.color_map = self.gen_pallete()

        self.freq_min = 2397.0  # FIXME: get from sensor
        self.freq_max = 2482.0
        self.power_min = -130.0
        self.power_max = -20.0
        self.grid_wide_freq = 5  # Mhz
        self.grid_wide_pwr = 10  # dBm

        self.ath_queue_in = ath_queue_in
        self.airtime_queue_in = airtime_queue_in

        self.heatmap = {}
        self.last_freq_cf = self.freq_max
        self.curr_hmp = {}
        self.save_tsf = 0
        self.persistence_window = 1000000  # in TU, since we use the TSF field als timebase
        self.bg_sample_count_limit = 100
        self.bg_sample_count = 0

        self.ui_update = True

        self.pwr_time_data = []
        self.tsf_start = 0
        logger.debug("ui setup done")

        self.sensor = None  # attach sensor instance here
        self.current_view = SimpleUI.view_unknown
        self.draw_grid()

        self.set_sensor(athscanner)

    def set_sensor(self, sensor):
        self.sensor = sensor
        self.freq_min, _ = min(sensor.get_supported_freqchan())
        self.freq_min -= 10  # add lower 1/2 channel wide to viewport
        self.freq_max, _ = max(sensor.get_supported_freqchan())
        self.freq_max += 10  # add uper 1/2 channel wide to viewport
        mode = sensor.get_mode()
        if mode == "chanscan":
            self.current_view = SimpleUI.view_cs
        elif mode == "background":
            self.current_view = SimpleUI.view_bg
        else:
            logger.warn("sensor is in an unsupported mode")
            self.current_view = SimpleUI.view_unknown
        self.update_caption()

    def main_loop(self):
        FPS = 15
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.quit()
                if event.type == pygame.KEYDOWN:
                    self.handle_keypress(event.key)

            if self.flush_data:
                self.flush_data = False
                self.flush()
                self.screen.fill(self.bg_color)
                if self.current_view is SimpleUI.view_cs or self.current_view is SimpleUI.view_bg:
                    self.draw_grid()

            pygame.display.update()
            self.update_data()  # does the heavy math 1/2

            if self.clean_screen:
                self.clean_screen = False
                self.heatmap = {}
                self.screen.fill(self.bg_color)
                if self.current_view is SimpleUI.view_cs or self.current_view is SimpleUI.view_bg:
                    self.draw_grid()

            if self.current_view is SimpleUI.view_cs or self.current_view is SimpleUI.view_bg:
                self.data_to_screen_freq()    # does the heavy math 2/2
            elif self.current_view is SimpleUI.view_hm:
                self.data_to_screen_power()  # does the heavy math 2/2

            if not self.ui_update:
                self.draw_centered_text(
                    "(UI Update Disabled)", self.width/2, self.height/2, (200, 200, 200), font_size=40)

                #self.clock.tick(FPS)


        # not running anymore
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        pygame.quit()

    def quit(self, *args):
        self.running = False

    def handle_keypress(self, key):

        # Exit
        if key == pygame.K_q or key == pygame.K_ESCAPE:
            self.quit()

        # Switch UI
        elif key == pygame.K_b:
            self.current_view = SimpleUI.view_bg
            self.flush_data = True
            self.update_caption()
            if self.sensor.get_mode() == "background":
                return
            self.sensor.set_mode_background()
            self.sensor.start()
        elif key == pygame.K_c:
            self.current_view = SimpleUI.view_cs
            self.flush_data = True
            self.update_caption()
            if self.sensor.get_mode() == "chanscan":
                return
            self.sensor.set_mode_chanscan()
            self.sensor.start()
        elif key == pygame.K_h:
            self.current_view = SimpleUI.view_hm
            self.flush_data = True
            self.update_caption()
            if self.sensor.get_mode() == "background":
                return
            self.sensor.set_mode_background()
            self.sensor.start()

        # Tune (if possible)
        elif key == pygame.K_LEFT:
            if self.sensor.get_mode() == "chanscan":
                return
            self.flush_data = True
            ch = self.sensor.current_chan - 1
            if ch < min([chan for (freq, chan) in self.sensor.get_supported_freqchan()]):
                ch = max([chan for (freq, chan) in self.sensor.get_supported_freqchan()])
            self.sensor.set_channel(ch)
        elif key == pygame.K_RIGHT:
            if self.sensor.get_mode() == "chanscan":
                return
            self.flush_data = True
            ch = self.sensor.current_chan + 1
            if ch > max([chan for (freq, chan) in self.sensor.get_supported_freqchan()]):
                ch = min([chan for (freq, chan) in self.sensor.get_supported_freqchan()])
            self.sensor.set_channel(ch)

        # Increase sample count or persistence
        elif key == pygame.K_UP:
            if self.sensor.get_mode() == "background":
                self.bg_sample_count_limit += 10
                self.bg_sample_count = 0
                self.flush_data = True
                logger.info("set bg persistence cnt to %d" % self.bg_sample_count_limit)
            else:
                sample_count = self.sensor.get_spectral_count() * 2
                if sample_count == 256:  # special case, 256 is not valid, set to last valid value
                    sample_count = 255
                if sample_count > 255:
                    sample_count = 1
                self.sensor.set_spectral_count(sample_count)
                self.update_caption()
        elif key == pygame.K_DOWN:
            if self.sensor.get_mode() == "background":
                self.bg_sample_count_limit -= 10
                if self.bg_sample_count_limit < 0:
                    self.bg_sample_count_limit = 0
                self.bg_sample_count = 0
                self.flush_data = True
                logger.info("set bg persistence cnt to %d" % self.bg_sample_count_limit)
            else:
                sample_count = self.sensor.get_spectral_count()
                if sample_count == 255:
                    sample_count = 256  # undo special case, see above
                sample_count //= 2
                if sample_count < 1:
                    sample_count = 255
                self.sensor.set_spectral_count(sample_count)
                self.update_caption()
        # Toggle HT20/HT40 mode
        elif key == pygame.K_m:
            self.flush_data = True
            logger.info("Toggle HT mode from %s " % self.sensor.current_ht_mode)
            if self.sensor.current_ht_mode == "HT20":
                self.sensor.set_HT_mode("HT40")
            else:
                self.sensor.set_HT_mode("HT20")

        # ignore unknown key
        else:
            return
        self.update_caption()

    def update_caption(self):
        caption = self.caption_prefix
        if self.current_view == SimpleUI.view_cs:
            caption += " - CS Mode (%d Samples)" % self.sensor.get_spectral_count()
        elif self.current_view == SimpleUI.view_bg:
            caption += " - BG Mode on Ch %d (%d MHz)" % (self.sensor.current_chan, self.sensor.current_freq)
        elif self.current_view == SimpleUI.view_hm:
            caption += " - Heatmap Mode on CH %d (%d MHz)" % (self.sensor.current_chan, self.sensor.current_freq)
        caption += " "+self.sensor.current_ht_mode+""
        if self.current_view == SimpleUI.view_hm:
            caption += " %d us/px" % self.tu_per_px
        #if self.sensor.dumping:
        #    caption += " [dumping to file]"
        pygame.display.set_caption(caption)

    @staticmethod
    def tsf_to_px(tsf_start, tsf, wx, wy, tu_per_px):
        tsf = tsf - tsf_start  # shift to origin
        tsf /= tu_per_px  # scale down (up?)
        (y, x) = divmod(tsf, wx)
        return int(x), int(y)

    @staticmethod
    def px_to_tsf(px, wx, tu_per_px):
        return px * tu_per_px * wx

    @staticmethod
    def frame_len_to_px(length, tu_per_px):
        px, _ = divmod(length, tu_per_px)
        return int(px)

    @staticmethod
    def pwr_to_color(pwr):
        dbm_min = -180
        dbm_max = -10
        # map 0-255 to dbm_max - min:
        if dbm_min < pwr < dbm_max:
            return int(((pwr - dbm_min) / (dbm_max - dbm_min)) * 255)
        return 0

    def flush(self):
        logger.debug("flush() qlen ath: %d" % self.ath_queue_in.qsize())
        while not self.ath_queue_in.empty():
            self.ath_queue_in.get()
        logger.debug("flush() qlen air: %d" % self.airtime_queue_in.qsize())
        while not self.airtime_queue_in.empty():
            self.airtime_queue_in.get()
        self.tsf_start = 0
        self.heatmap = {}

    def gen_pallete(self):
        # create a 256-color gradient from blue->green->white
        start_col = (0.1, 0.1, 1.0)
        mid_col = (0.1, 1.0, 0.1)
        end_col = (1.0, 1.0, 1.0)

        colors = [0] * 256
        for i in range(0, 256):
            if i < 128:
                sf = (128.0 - i) / 128.0
                sf2 = i / 128.0
                colors[i] = (start_col[0] * sf + mid_col[0] * sf2,
                             start_col[1] * sf + mid_col[1] * sf2,
                             start_col[2] * sf + mid_col[2] * sf2)
            else:
                sf = (256.0 - i) / 128.0
                sf2 = (i - 128.0) / 128.0
                colors[i] = (mid_col[0] * sf + end_col[0] * sf2,
                             mid_col[1] * sf + end_col[1] * sf2,
                             mid_col[2] * sf + end_col[2] * sf2)
        return colors

    def sample_to_viewport(self, freq, power, wx, wy):

        # normalize both frequency and power to [0,1] interval, and
        # then scale by window size
        freq_normalized = (freq - self.freq_min) / (self.freq_max - self.freq_min)
        freq_scaled = freq_normalized * wx

        power_normalized = (power - self.power_min) / (self.power_max - self.power_min)
        power_scaled = power_normalized * wy

        # flip origin to bottom left for y-axis
        power_scaled = wy - power_scaled

        return freq_scaled, power_scaled

    def draw_centered_text(self, text, x, y, color, font_size=20):
        #font = pygame.font.SysFont("monospace", 20)
        font = pygame.font.Font(None, font_size)
        label = font.render(text, 1, color)
        sx, sy = font.size(text)
        self.screen.blit(label, (x - sx/2, y - sy/2))

    def draw_grid(self):
        # horizontal lines (frequency)
        for freq in range(int(self.freq_min), int(self.freq_max), self.grid_wide_freq):
            start_xy = self.sample_to_viewport(freq, self.power_min, self.width, self.height)
            end_xy = self.sample_to_viewport(freq, self.power_max, self.width, self.height)
            pygame.draw.line(self.screen, self.line_color, start_xy, end_xy)
            if freq != self.freq_min and freq != self.freq_max:
                self.draw_centered_text("%d" % freq, start_xy[0], 20, self.text_color)

        # vertical lines (power)
        for power in range(int(self.power_min), int(self.power_max), self.grid_wide_pwr):
            start_xy = self.sample_to_viewport(self.freq_min, power, self.width, self.height)
            end_xy = self.sample_to_viewport(self.freq_max, power, self.width, self.height)
            pygame.draw.line(self.screen, self.line_color, start_xy, end_xy)
            if power != self.power_min and power != self.power_max:
                self.draw_centered_text("%d dBm" % power, 35, start_xy[1], self.text_color)

    def update_data(self):
        self.bg_sample_count = 0
        hmp = self.heatmap
        while True:
            try:
                (ts, data) = self.ath_queue_in.get(block=False)
            except queue.Empty:
                break

            if self.current_view is SimpleUI.view_cs or self.current_view is SimpleUI.view_bg:
                (tsf, freq_cf, noise, rssi, pwr) = data
                if self.current_view is SimpleUI.view_cs:
                    if freq_cf < self.last_freq_cf:
                        self.clean_screen = True
                    self.last_freq_cf = freq_cf
                elif self.current_view is SimpleUI.view_bg:
                    if tsf > self.save_tsf + self.persistence_window:
                        self.save_tsf = tsf + self.persistence_window
                        self.clean_screen = True
                    if self.bg_sample_count == self.bg_sample_count_limit:
                        continue
                    self.bg_sample_count += 1
                else:
                    continue
                for freq_sc, sigval in pwr.items():
                    if sigval <= self.power_min:  # skip invisible pixel
                        continue
                    if freq_sc not in hmp.keys():
                        hmp[freq_sc] = {}
                    arr = hmp[freq_sc]
                    mody = math.ceil(sigval*2.0)/2.0
                    arr.setdefault(mody, 0)  # pwr level is unknown
                    arr[mody] += 1.0  # count how often, a pwr level occurs per freq_sc
            elif self.current_view is SimpleUI.view_hm:
                (tsf, freq_cf, noise, rssi, pwr) = data
                pwr_channel = self.pwr_of_channel(pwr)
                self.pwr_time_data.append((tsf, -1, pwr_channel, None))

        while True:
            try:
                data = self.airtime_queue_in.get(block=False)
            except queue.Empty:
                break
            if self.current_view is SimpleUI.view_hm:
                (tsf, length, pwr, _, is_fcs_bad, _) = data
                self.pwr_time_data.append((tsf, length, pwr, is_fcs_bad))
        self.heatmap = hmp

    def pwr_of_channel(self, pwr_per_subcarrier):
        # see M.Rademacher
        rssi_sum = 0
        for freq, pwr in pwr_per_subcarrier.items():
            rssi_sum += 10 ** (pwr / 10)
        if rssi_sum != 0:
            rssi_channel = 10 * math.log10(rssi_sum)
            return rssi_channel
        else:
            return -200   # fixme: better idea?

    def data_to_screen_freq(self):
        zmax = 0
        for center_freq in self.heatmap.keys():
            last_pwr = -float('inf')
            for power, value in self.heatmap[center_freq].items():
                if power > last_pwr:
                    last_pwr = power
                if zmax < value:
                    zmax = self.heatmap[center_freq][power]

        if not zmax:
            zmax = 1

        for center_freq in self.heatmap.keys():
            for power, value in self.heatmap[center_freq].items():
                posx, posy = self.sample_to_viewport(center_freq, power, self.width, self.height)
                color = self.color_map[int(len(self.color_map) * value / zmax) & 0xff]
                c = (color[0]*255, color[1]*255, color[2]*255)
                pygame.draw.rect(self.screen, c, (posx, posy, 2, 2))

    def data_to_screen_power(self):
        max_y = 0
        for (tsf, length, pwr, is_fcs_bad) in self.pwr_time_data:
            if self.tsf_start == 0:  # first sample
                self.tsf_start = tsf

            x, y = self.tsf_to_px(self.tsf_start, tsf, self.width, self.height, self.tu_per_px)
            max_y = y
            if length == -1:  # spectral sample. set single pixel
                intensity = self.pwr_to_color(pwr)
                #print "sample:", x,y, intensity
                c = (0, intensity, 0)
                #print(((x, y), c), pwr)
                #pygame.draw.rect(self.screen, c, (x, y, 2, 2))
                self.screen.set_at((x, y), c)
                #pygame.display.update()

            else:
                intensity = self.pwr_to_color(float(pwr))
                if is_fcs_bad:
                    c = (intensity, 0, 0) # Red
                else:
                    c = (0, 0, intensity)  # Blue
                if float(pwr) == -2.0:
                    c = (255, 0, 0)
                    logger.warn("pwr less wifi sample detected")

                px = self.frame_len_to_px(length, self.tu_per_px)
                #print "frame: ", x,y, pwr, intensity, px
                i = 0
                while px > i:
                    if x + i >= self.width:
                        y2, x2 = divmod(x+i, self.width)
                        self.screen.set_at((x2, y+y2), c)
                        if max_y < y+y2:
                            max_y = y+y2
                            #pygame.draw.rect(self.screen, c, (x2, y+y2, 2, 2))
                    else:
                        self.screen.set_at((x+i, y), c)
                        #pygame.draw.rect(self.screen, c, (x+i, y, 2, 2))
                    i += 1
        if max_y >= self.height-10:  # 10 margin ?
            y_px_to_scroll = - self.height / 10
            tsf_scroll = self.px_to_tsf(y_px_to_scroll, self.width, self.tu_per_px)
            self.tsf_start -= tsf_scroll
            # print "scroll", tsf - self.tsf_start, tsf_scroll
            self.screen.scroll(0, int(y_px_to_scroll))
            pygame.draw.rect(self.screen, self.bg_color, (0, self.height+y_px_to_scroll, self.width, self.height))

        self.pwr_time_data = []

if __name__ == '__main__':
    athss_queue = mp.Queue()
    airtime_queue = mp.Queue()
    scanner = AthSpectralScanner(interface=sys.argv[1])
    scanner.set_spectral_short_repeat(0)
    scanner.set_mode("background")
    scanner.set_channel(1)
    airtimecalc = AirtimeCalculator(monitor_interface=sys.argv[1], output_queue=airtime_queue)
    decoder = AthSpectralScanDecoder()
    decoder.set_number_of_processes(1)
    decoder.set_output_queue(athss_queue)
    hub = DataHub(scanner=scanner, decoder=decoder)

    decoder.start()
    hub.start()
    airtimecalc.start()
    scanner.start()

    ui = SimpleUI(athscanner=scanner, ath_queue_in=athss_queue, airtime_queue_in=airtime_queue)
    ui.main_loop()  # UI takes care of events, blocking

    scanner.stop()
    hub.stop()
    airtimecalc.stop()
