# TwitchTTS
트위치 채팅 읽어주는 프로그램

다운 링크 ([https://github.com/sugial/TwitchTTS/releases/download/TwitchTTS_Fixed/TwitchTTS.zip](https://github.com/sugial/TwitchTTS/releases/download/TwitchTTS_Fixed/TwitchTTS.zip)) 23.06.25 수정

## 설치법
### 필요사양 (실행 안될 시 컴파일 용)
``` Python 3.10 ```
``` 
pip install numpy
pip install sounddevice
pip install PyQt5
pip install --upgrade google-cloud-texttospeech
```

- TwitchTTS.py 실행시 twitch.ui와 user.txt는 같은 폴더에 있어야 합니다.

``` python TwitchTTS.py ```


## 사용법
1. 구글 계정이 필요합니다. 다음 링크에 접속해주세요. (https://youngq.tistory.com/35)

2. 상단 링크의 내용 중 **2) API 설정하기** 까지만 수행해주세요.

2-1. 다음 링크에서 **.json 파일**을 생성 후 저장해주세요. 해당 링크의 10번 항목부터 진행하시면 됩니다. (https://noanomal.tistory.com/entry/%EA%B5%AC%EA%B8%80-%EB%B2%88%EC%97%AD-api-%EC%82%AC%EC%9A%A9%EC%9D%84-%EC%9C%84%ED%95%9C-json-%ED%82%A4-%ED%8C%8C%EC%9D%BC-%EB%8B%A4%EC%9A%B4%EB%A1%9C%EB%93%9C-%EB%B0%A9%EB%B2%95)

3. 생성된 비공개 **.json 파일**을 저장해주세요. 프로그램 실행시 필요합니다.

4. 프로그램 실행 화면에서 **Open GoogleTTS** 버튼을 눌러 저장한 json 파일을 열어주세요.
<img src="https://github.com/sugial/TwitchTTS/blob/main/ReadMe/01_ttsmain2.png">

5. json 파일 읽기 성공이 뜨면 하단의 채널명에 접속할 채널 주소 (자기 아이디)를 적고 **채팅방 연결** 버튼을 눌러주세요.
<img src="https://github.com/sugial/TwitchTTS/blob/main/ReadMe/02_ttsmain.png">

6. TTS가 동작하지 않는다면, **연결 끊기** 버튼을 누르고 잠시 기다렸다가 다시 채팅방에 연결하시면 됩니다. 그래도 동작하지 않으면, 껐다 키는 것을 권장드립니다.

7. **사용자 새로고침** 버튼을 누르면, 왼쪽 박스에서 채팅에 참여하였던 사람들의 아이디 리스트를 확인할 수 있습니다. 채팅을 친 사람이 목록에 보이지 않는다면 눌러주세요.
<img src="https://github.com/sugial/TwitchTTS/blob/main/ReadMe/03_ttsmain2.png">

8. 사용자별로 TTS 목소리 조절이 가능합니다. 타입은 남성 4종류, 여성 4종류가 있으며, 속도는 0.3&#45;3.0, 피치는 0.0&#45;2.0을 지원합니다. 기본 속도와 피치는 1.0, 1.0입니다.

9. 사용자별 설정을 바꾼 후 **업데이트** 버튼을 눌러야 적용됩니다. **Randomize** 버튼은 타입, 속도, 피치를 랜덤하게 변경합니다.
<img src="https://github.com/sugial/TwitchTTS/blob/main/ReadMe/04_ttsmain.png">

<!--
https://cloud.google.com/text-to-speech/docs/before-you-begin?hl=ko

https://youngq.tistory.com/35

여기서 구글 API 발급 받고 json 파일 저장 후 사용

채팅방 연결했는데 소리가 안날 경우 연결 끊기 후 다시 연결

유저 ID가 안보이면 사용자 새로고침 누르면 나옴 -->
