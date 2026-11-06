# 사규검색 안드로이드 앱

사규검색 사이트(https://ianflyhigher.github.io/iiac-rules-search/)를 전체 화면으로 여는 WebView 앱입니다.
사규 데이터는 사이트에서 받아오므로 사규가 갱신돼도 앱을 다시 설치할 필요가 없습니다.

* `android/` 아래가 바뀌면 GitHub Actions(`android.yml`)가 APK를 빌드해 Releases에 올립니다.
* 받기: https://github.com/Ianflyhigher/iiac-rules-search/releases/latest/download/sagyu.apk
* 서명키는 저장소에 없습니다. 저장소 Secrets `ANDROID_KEYSTORE_B64`, `ANDROID_KEYSTORE_PASSWORD` 로 넣습니다.
  원본 키는 관리자 PC에 따로 보관하세요. 키가 바뀌면 기존 앱을 지우고 새로 설치해야 합니다.
