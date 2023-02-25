import sys
import os
import re
import random
import time
import struct
import numpy

from queue import Queue
import sounddevice as sd

import socket

from google.cloud import texttospeech

from PyQt5 import uic

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from_class = uic.loadUiType("twitch.ui")[0]

class TTSReadThread(QThread):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.queue = parent.chat_queue

        self.power = True

        self.setupTTS()

        self.chkKor = re.compile('[ㄱ-ㅎㅏ-ㅣ가-힣]')
        self.chkJpn = re.compile('[ぁ-ゔァ-ヴー々〆〤一-龥]')


    def addEffect(self, audio_data):
        def _read_data_chunk(fid, format_tag, channels, bit_depth, is_big_endian,
                             block_align, ofs, mmap=False):

            if is_big_endian:
                fmt = '>'
            else:
                fmt = '<'

            offset = ofs

            # Size of the data subchunk in bytes
            size = struct.unpack(fmt + 'I', fid[offset:offset + 4])[0]
            offset += 4

            # Number of bytes per sample (sample container size)
            bytes_per_sample = block_align // channels
            n_samples = size // bytes_per_sample

            if format_tag == 0x0001:
                if 1 <= bit_depth <= 8:
                    dtype = 'i1'  # WAV of 8-bit integer or less are unsigned
                elif bytes_per_sample in {3, 5, 6, 7}:
                    # No compatible dtype.  Load as raw bytes for reshaping later.
                    dtype = 'V1'
                elif bit_depth <= 64:
                    # Remaining bit depths can map directly to signed numpy dtypes
                    dtype = f'{fmt}i{bytes_per_sample}'
                else:
                    raise ValueError("Unsupported bit depth: the WAV file "
                                     f"has {bit_depth}-bit integer data.")

            start = offset
            if not mmap:
                data = numpy.frombuffer(fid[offset:offset + size], dtype=dtype)
                offset += size

            offset = _handle_pad_byte(fid, size, offset)

            if channels > 1:
                data = data.reshape(-1, channels)
            return data

        def _handle_pad_byte(fid, size, offset):
            # "If the chunk size is an odd number of bytes, a pad byte with value zero
            # is written after ckData." So we need to seek past this after each chunk.
            if size % 2:
                res = offset - 1
            else:
                res = offset
            return res

        def _read_fmt_chunk(fid, is_big_endian, ofs):
            if is_big_endian:
                fmt = '>'
            else:
                fmt = '<'

            offset = ofs

            size = struct.unpack(fmt + 'I', fid[offset:offset + 4])[0]
            offset += 4
            # print ('size', size)

            if size < 16:
                raise ValueError("Binary structure of wave file is not compliant")

            res = struct.unpack(fmt + 'HHIIHH', fid[offset:offset + 16])
            bytes_read = 16
            offset += 16
            # print ('res', res)

            format_tag, channels, fs, bytes_per_second, block_align, bit_depth = res

            if format_tag == 0xFFFE and size >= (16 + 2):
                ext_chunk_size = struct.unpack(fmt + 'H', fid[offset:offset + 2])[0]
                offset += 2
                bytes_read += 2
                if ext_chunk_size >= 22:
                    extensible_chunk_data = fid[offset:offset + 22]
                    offset += 22
                    bytes_read += 22
                    raw_guid = extensible_chunk_data[2 + 4:2 + 4 + 16]
                    # GUID template {XXXXXXXX-0000-0010-8000-00AA00389B71} (RFC-2361)
                    # MS GUID byte order: first three groups are native byte order,
                    # rest is Big Endian
                    if is_big_endian:
                        tail = b'\x00\x00\x00\x10\x80\x00\x00\xAA\x00\x38\x9B\x71'
                    else:
                        tail = b'\x00\x00\x10\x00\x80\x00\x00\xAA\x00\x38\x9B\x71'
                    if raw_guid.endswith(tail):
                        format_tag = struct.unpack(fmt + 'I', raw_guid[:4])[0]
                else:
                    raise ValueError("Binary structure of wave file is not compliant")

            # print(offset)

            # move file pointer to next chunk
            if size > bytes_read:
                offset += (size - bytes_read)
                # fid.read(size - bytes_read)

            # fmt should always be 16, 18 or 40, but handle it just in case
            offset = _handle_pad_byte(fid, size, offset)

            if format_tag == 0x0001:
                if bytes_per_second != fs * block_align:
                    raise ValueError("WAV header is invalid: nAvgBytesPerSec must"
                                     " equal product of nSamplesPerSec and"
                                     " nBlockAlign, but file has nSamplesPerSec ="
                                     f" {fs}, nBlockAlign = {block_align}, and"
                                     f" nAvgBytesPerSec = {bytes_per_second}")

            return (size, format_tag, channels, fs, bytes_per_second, block_align,
                    bit_depth, offset)

        def _skip_unknown_chunk(fid, is_big_endian, ofs):
            if is_big_endian:
                fmt = '>I'
            else:
                fmt = '<I'
            offset = ofs

            data = fid[offset:offset + 4]
            offset += 4
            # call unpack() and seek() only if we have really read data from file
            # otherwise empty read at the end of the file would trigger
            # unnecessary exception at unpack() call
            # in case data equals somehow to 0, there is no need for seek() anyway

            if data:
                size = struct.unpack(fmt, data)[0]
                # print(data, offset, size)
                offset = offset + size
                # fid.seek(size, 1)
                offset = _handle_pad_byte(fid, size, offset)
            return offset

        # parse audio data and process
        offset = 0
        str1 = audio_data[offset:offset + 4]
        offset += 4

        if str1 == b'RIFF':
            is_big_endian = False
            fmt = '<I'

        file_size = struct.unpack(fmt, audio_data[offset:offset + 4])[0] + 8
        offset += 4

        str2 = audio_data[offset:offset + 4]
        offset += 4

        # print (str1, file_size, str2)

        # read the next chunk
        for i in range(3):
            chunk_id = audio_data[offset:offset + 4]
            offset += 4
            # print (chunk_id)

            if chunk_id == b'fmt ':
                fmt_chunk_received = True
                fmt_chunk = _read_fmt_chunk(audio_data, is_big_endian, offset)
                format_tag, channels, fs = fmt_chunk[1:4]
                # format_tag = 1 # why?
                bit_depth = fmt_chunk[6]
                block_align = fmt_chunk[5]
                offset = fmt_chunk[7]
            elif chunk_id == b'fact':
                offset = _skip_unknown_chunk(audio_data, is_big_endian, offset)
            elif chunk_id == b'data':
                data_chunk_received = True
                # if not fmt_chunk_received:
                #     raise ValueError("No fmt chunk before data")
                data = _read_data_chunk(audio_data, format_tag, channels, bit_depth,
                                        is_big_endian, block_align, offset)

        process = data

        return process

    def setupTTS(self):
        # TTS 파트 테스트 --> 구글 API 파일 읽어올 수 있도록 할 것
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.parent.apiname[0]

        self.client = texttospeech.TextToSpeechClient()

    def run(self):
        while self.power:
            if self.queue.qsize() > 0:
                try:
                    [user_id, content, cur_type, cur_speed, cur_pitch] = self.queue.get()
                    # print (self.queue.get(), self.queue.qsize())

                    self.doTTS = self.parent.ttsEnable  # TTS 허용
                    tts_volume = self.parent.ttsVolume

                    # print('volume', tts_volume)

                    if len(content) > 0 and self.doTTS:
                        if len(content) > 50:  # 50글자 이상은 스킵
                            continue
                        if content[0] == '!': # !로 시작하는 명령어 스킵
                            continue


                        # Select the type of audio file you want returned

                        # if len(self.chkKor.findall(content[:10])) > 0:
                        if self.chkKor.search(content):
                            v_code = "ko-KR"
                            if int(cur_type) == 1:
                                v_name = "ko-KR-Standard-A"
                            elif int(cur_type) == 2:
                                v_name = "ko-KR-Standard-B"
                            elif int(cur_type) == 3:
                                v_name = "ko-KR-Standard-C"
                            elif int(cur_type) == 4:
                                v_name = "ko-KR-Standard-D"
                            elif int(cur_type) == 5:
                                v_name = "ko-KR-Wavenet-A"
                            elif int(cur_type) == 6:
                                v_name = "ko-KR-Wavenet-B"
                            elif int(cur_type) == 7:
                                v_name = "ko-KR-Wavenet-C"
                            elif int(cur_type) == 8:
                                v_name = "ko-KR-Wavenet-D"
                        # elif len(self.chkJpn.findall(content[:10])) > 0:
                        elif self.chkJpn.search(content):
                            v_code = "ja-JP"
                            if int(cur_type) == 1:
                                v_name = "ja-JP-Standard-A"
                            elif int(cur_type) == 2:
                                v_name = "ja-JP-Standard-B"
                            elif int(cur_type) == 3:
                                v_name = "ja-JP-Standard-C"
                            elif int(cur_type) == 4:
                                v_name = "ja-JP-Standard-D"
                            elif int(cur_type) == 5:
                                v_name = "ja-JP-Wavenet-A"
                            elif int(cur_type) == 6:
                                v_name = "ja-JP-Wavenet-B"
                            elif int(cur_type) == 7:
                                v_name = "ja-JP-Wavenet-C"
                            elif int(cur_type) == 8:
                                v_name = "ja-JP-Wavenet-D"
                        else:
                            v_code = "en-US"
                            if int(cur_type) == 1:
                                v_name = "en-US-Standard-C"
                            elif int(cur_type) == 2:
                                v_name = "en-US-Standard-E"
                            elif int(cur_type) == 3:
                                v_name = "en-US-Standard-A"
                            elif int(cur_type) == 4:
                                v_name = "en-US-Standard-B"
                            elif int(cur_type) == 5:
                                v_name = "en-US-Wavenet-C"
                            elif int(cur_type) == 6:
                                v_name = "en-US-Wavenet-E"
                            elif int(cur_type) == 7:
                                v_name = "en-US-Wavenet-A"
                            elif int(cur_type) == 8:
                                v_name = "en-US-Wavenet-B"

                        self.voice = texttospeech.VoiceSelectionParams(
                            language_code=v_name,
                            # ssml_gender=1,
                            name=v_name  # name을 바꾸는 것으로 성별 및 목소리 타입 변경 가능
                            # 가능한 name은 ko-KR-Standard-A, ko-KR-Wavenet-A로 ABCD 4종류, CD가 남자
                            # ssml_gender=texttospeech.SsmlVoiceGender.MALE
                        )

                        self.audio_config = texttospeech.AudioConfig(
                            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                            # audio_encoding=texttospeech.AudioEncoding.ALAW,
                            speaking_rate=cur_speed,
                            pitch=cur_pitch,
                            volume_gain_db=tts_volume
                        )

                        self.synthesis_input = texttospeech.SynthesisInput(text=content)

                        response = self.client.synthesize_speech(
                            input=self.synthesis_input, voice=self.voice, audio_config=self.audio_config
                        )


                        audio = self.addEffect(response.audio_content)
                        sd.play(audio, 24000)
                        sd.wait()

                        time.sleep(0.2)
                except:
                    pass
                    # print("TTS Error!")
            time.sleep(0.2)

    def stop(self):
        self.power = False
        self.quit()
        self.wait(2000)


# 채팅 irc 로그 읽고 계속 돌릴 스레드 테스트
class Thread(QThread):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent

        self.s = parent.s
        self.power = True

        self.queue = parent.chat_queue

        self.regex = re.compile(
            '^(?:@(?P<tags>(?:.+?=.*?)(?:;.+?=.*?)*) )?(?::(?P<source>[^ ]+?) )?(?P<command>[0-9]{3}|[a-zA-Z]+)(?: (?P<params>.+?))?(?: :(?P<content>.*))?$')

        self.user_info = parent.user_dict

        self.connectIRC()

        self.data = ""

        self.doTTS = True

    def connectIRC(self):  # 트위치 IRC 접속 --> 나중에 새 gui로 만들기
        HOST = "irc.chat.twitch.tv"

        PORT = 6667
        NICK = "justinfan12345678912345"  # 채팅 안쓰고 접속만 할 수 있음
        self.CHAN = "#" + str(self.parent.lineEdit.text())

        # self.s = socket.socket()
        self.s.connect((HOST, PORT))
        self.s.send("NICK {}\r\n".format(NICK).encode())
        self.s.send("CAP REQ :twitch.tv/tags twitch.tv/commands\r\n".encode())
        self.s.send("JOIN {}\r\n".format(self.CHAN).encode())

    def run(self):
        cnt = 0
        # print (self.user_info)
        while self.power:
            try:
                resp = self.s.recv(8192)
                # print(resp)
                # :foo!foo@foo.tmi.twitch.tv JOIN #bar\r\n

                self.data = resp.decode()  # 받아온 메시지 decode 하는 파트
                message = self.data.split('\r\n')[:-1]

                msg_cnt = 0

                for i in message:
                    # print (i)
                    if msg_cnt > 3:
                        break

                    matches = self.regex.match(i)

                    # Tags : 데이터 리스트들, src -> 채팅 아이디, cmd -> PRIVMSG,
                    [tags, source, command, params, content] = matches.groups()

                    if command == 'PING':
                        self.s.send("PONG :tmi.twitch.tv\r\n".encode())
                        break

                    if command != 'PRIVMSG':
                        continue

                    if tags == None:
                        continue

                    user_id = source.split('!')[0]

                    # 새로운 id인 경우 dict에 기본 정보 추가
                    if not self.user_info.get(user_id):
                        self.user_info[user_id] = [1.0, 1.0, 0.0]
                        cur_type = 1
                        cur_speed = 1.0
                        cur_pitch = 0.0
                    else:
                        [cur_type, cur_speed, cur_pitch] = self.user_info[user_id]

                    tag_list = dict(tag.split('=', 1) for tag in tags.split(';'))

                    nickname = tag_list.get('display-name')
                    emote_info = tag_list.get('emotes')

                    if not nickname:
                        continue
                    # print ('chk', nickname, emote_info)

                    # 이모티콘이 있을 시 삭제하기
                    if emote_info is not None and len(emote_info) > 5:
                        emote_list = emote_info.split('/')
                        # print('info', emote_list)
                        emote_idx = []
                        for loc in emote_list:
                            location = loc.split(':')[1]
                            loc_list = location.split(',')

                            for l in loc_list:
                                [st, ed] = l.split('-')
                                emote_idx.append(int(st))
                                emote_idx.append(int(ed))

                        emote_idx.reverse()
                        # print (emote_idx)
                        for k in range(0, len(emote_idx), 2):
                            # print (emote_idx[k+1], emote_idx[k])
                            content = content[:emote_idx[k + 1]] + content[emote_idx[k] + 2:]
                            # content[emote_idx[k+1]:emote_idx[k]+1] = ""

                    # 긴 링크는 링크로
                    content = re.sub(
                        r'https?://(www.)?[-a-zA-Z0-9@:%._+~#=]{2,256}.[a-z]{2,4}\b([-a-zA-Z0-9@:%_+.~#?&/=]*)', '링크',
                        content)

                    # ㅋ는 3번만
                    content = re.sub(r'ㅋ{3,}', 'ㅋㅋㅋ', content)
                    content = re.sub(r'z{3,}', 'zzz', content)
                    content = re.sub(r'Z{3,}', 'ZZZ', content)
                    content = re.sub(r'@{4,}', '@@@@', content)
                    # 'https?:\\(www\.)?[-a-zA-Z0-9@:%._+~#=]{2,256}\.[a-z]{2,4}\b([-a-zA-Z0-9@:%_+.~#?&/=]*)'
                    # print(nickname, user_id, ":", content)

                    # 봇은 tts 안넘기고 패스
                    if user_id == 'bbangddeock' or user_id == 'nightbot' or user_id == 'ssakdook':
                        continue

                    if self.queue.qsize() > 20:
                        continue

                    self.queue.put([user_id, content, cur_type, cur_speed, cur_pitch])

                    msg_cnt += 1
            except:
                pass
                # print("IRC Error!")

            time.sleep(0.05)

    def stop(self):
        self.power = False
        self.quit()
        self.wait(2000)


# 사용자 아이디별 db
# id, type, speed, pitch
# 기본은 id 1 1.0 1.0
# volume은 전역 설정


class MyApp(QWidget, from_class):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.chat_queue = Queue()
        self.s = socket.socket()  # socket

        self.user_dict = {}
        self.read_user_info()
        self.init_voice_stat()

        self.oldComboText = next(iter(self.user_dict))

        self.ttsVolume = 0.0
        self.spinBox_volume.valueChanged.connect(self.tts_volume_change)

        self.ttsEnable = True
        self.echoEnable = False

        self.checkBox.stateChanged.connect(self.tts_enable)

        self.pushButton.clicked.connect(self.print_log)
        self.pushButton_deque.clicked.connect(self.delete_queue)
        self.pushButton_close.clicked.connect(self.disconnect_irc)
        self.pushButton_reloaduser.clicked.connect(self.user_reload)
        self.pushButton_random.clicked.connect(self.tts_custom_randomize)
        self.pushButton_ttsapi.clicked.connect(self.open_google_tts)

        self.comboBox.activated[str].connect(self.read_custom_voice)

        self.pushButton_update.clicked.connect(self.update_custom_voice)


    def open_google_tts(self):
        self.apiname = QFileDialog.getOpenFileName(self,"Read TTS API",".",'json(*.json)')

        if self.apiname[0]:
            self.label_status.setText("json 파일 읽기 성공")
            self.pushButton.setEnabled(True)
            self.pushButton_deque.setEnabled(True)
            self.pushButton_close.setEnabled(True)
            self.pushButton_reloaduser.setEnabled(True)
            self.pushButton_random.setEnabled(True)
            self.pushButton_update.setEnabled(True)
            self.comboBox.setEnabled(True)
        else:
            self.label_status.setText("파일 읽기 실패")

    def rand_speed(self):
        mu = 1
        sigma = 0.2

        s = numpy.random.normal(mu, sigma)
        rnd_spd = numpy.round(s, 1)

        if rnd_spd < 0.3:
            rnd_spd = 0.3
        elif rnd_spd > 3.0:
            rnd_spd = 3.0

        return rnd_spd
# -20 20  +20 / 20 -> 0 40 -> 0 2
    def rand_pitch(self):
        mu = 0
        sigma = 5

        s = numpy.random.normal(mu, sigma)
        s = (s + 20) / 20.0
        rnd_pit = numpy.round(s, 1)

        if rnd_pit < 0.0:
            rnd_pit = 0.0
        elif rnd_pit > 2.0:
            rnd_pit = 2.0

        return rnd_pit

    def tts_custom_randomize(self):
        rnd_type = random.randint(1, 8)  # 1~8 사이의 정수

        # print (random.random()) # 0~1 사이
        # 속도 범위는 1이 기본, 0.6~1.4를 범위내로
        # 피치 범위는 -20~20이고 0이 기본. -10~10 사이가 나오도록

        # new random param
        rnd_speed = self.rand_speed()
        rnd_pitch = self.rand_pitch()

        self.spinBox.setValue(rnd_type)
        self.doubleSpinBox.setValue(rnd_speed)
        self.doubleSpinBox_2.setValue(rnd_pitch)

        self.lineEdit_2.setText("!타입:%d, 속도:%.1f, 피치:%.1f" % (rnd_type, rnd_speed,rnd_pitch))

        self.update_custom_voice()

    def tts_volume_change(self):
        self.ttsVolume = float(self.spinBox_volume.value())

    def tts_enable(self, state):
        if state == Qt.Checked:
            self.ttsEnable = True
        else:
            self.ttsEnable = False

    def update_custom_voice(self):
        cur_id = str(self.comboBox.currentText())
        self.oldComboText = cur_id
        cur_type = self.spinBox.value()
        cur_speed = self.doubleSpinBox.value()
        cur_pitch = self.doubleSpinBox_2.value()
        self.user_dict[cur_id] = [cur_type, cur_speed, cur_pitch]

        self.user_reload()

    def init_voice_stat(self):
        cur_id = str(self.comboBox.currentText())
        [type, speed, pitch] = self.user_dict[cur_id]
        self.spinBox.setValue(int(type))
        self.doubleSpinBox.setValue(speed)
        self.doubleSpinBox_2.setValue(pitch)

    def read_custom_voice(self, text):
        [type, speed, pitch] = self.user_dict[text]
        # print (type, speed, pitch)
        self.spinBox.setValue(int(type))
        self.doubleSpinBox.setValue(speed)
        self.doubleSpinBox_2.setValue(pitch)

        self.lineEdit_2.setText("!타입:%d, 속도:%.1f, 피치:%.1f"%(int(type), speed, pitch))

    # 사용자 아이디 저장된 파일 읽어서 초기화시키기
    def read_user_info(self):
        f = open('user.txt', 'r')  # 등록 인원수, 각 정보
        num_user = int(f.readline())

        for i in range(num_user):
            user_info = f.readline()
            info_detail = user_info.split(' ')
            # print (info_detail)
            user_id = info_detail[0]
            self.comboBox.addItem(user_id)

            v_type = float(info_detail[1])
            v_speed = float(info_detail[2])
            v_pitch = float(info_detail[3])

            u_info = [v_type, v_speed, v_pitch]

            # print (user_id, v_type, v_speed, v_pitch)
            self.user_dict[user_id] = u_info
            # dict(tag.split('=', 1) for tag in tags.split(';'))

        # print (self.user_dict)
        f.close()
        # pass

    def delete_queue(self):
        while self.chat_queue.qsize() > 0:
            self.chat_queue.get()

    def disconnect_irc(self):
        self.h2.stop()
        time.sleep(2)
        self.h1.stop()
        time.sleep(2)
        self.s.close()

        self.s = socket.socket()

    def user_reload(self):
        # 현재 유저 정보 출력만
        self.comboBox.clear()

        # print (self.user_dict, len(self.user_dict))

        id_list = sorted(self.user_dict.items())
        # print (id_list)

        # 새로 고침하면 현재 세팅 저장 후 다시 불러오기
        f = open('user.txt', 'w')  # 등록 인원수, 각 정보
        f.write('%d\n' % len(self.user_dict))

        for i in id_list:
            name = i[0]
            data = i[1]
            # print (name, data)
            # data = self.user_dict[i]
            self.comboBox.addItem(name)
            # print (i, data)
            # print (i, data[0], data[1], data[2])
            f.write('%s %.1f %.1f %.1f\n' % (name, data[0], data[1], data[2]))

        f.close()

        # 직전 사람 이름으로 커서 위치
        self.comboBox.setCurrentText(self.oldComboText)

    def print_log(self):
        self.h1 = Thread(self)
        self.h1.start()
        # self.textBrowser.append("테스트") # 텍스트 브라우저에 하나씩 출력

        self.h2 = TTSReadThread(self)
        self.h2.start()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = MyApp()
    ex.show()
    sys.exit(app.exec_())

# pyinstaller 설치 명령어 pyinstaller --additional-hooks-dir ./hooks/ -w --clean --onefile TwitchTTS.py