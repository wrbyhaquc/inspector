import { lang } from '../i18n'

// The tutorial (docs/tutorial.md, docs/tutorial.zh-TW.md): from an empty project to a pack. Pages link to the chapter
// that explains them, in the page's language where there is one (Chinese pages: the Chinese tutorial, else English).
const DOC = 'https://github.com/wrbyhaquc/inspector/blob/main/docs/'
const ZH = ['1-準備', '2-接上攝影機', '3-錄一段畫面', '4-定義要看的狀態', '5-回答問題檢查判斷準不準', '6-輸出控制設備的方式',
  '7-子腳本一件一件的動作', '8-主腳本什麼時候做什麼', '9-執行', '10-排程定時餵魚', '11-操作面板給現場的人用', '12-匯出方案包裝到另一台']
const EN = ['1-get-ready', '2-connect-the-camera', '3-record-a-while', '4-define-the-states-to-watch',
  '5-answer-questions-how-well-is-it-judged', '6-an-output-how-equipment-is-driven', '7-sub-scripts-one-action-each',
  '8-the-main-script-what-to-do-when', '9-run', '10-schedules-feeding-on-time', '11-the-operation-panel-for-the-people-on-site',
  '12-export-the-pack-install-it-elsewhere']

/** the tutorial, at chapter ch (1-12) or its start */
export function tutorialLink(ch?: number) {
  const zh = lang.startsWith('zh')
  const page = DOC + (zh ? 'tutorial.zh-TW.md' : 'tutorial.md')
  return ch ? `${page}#${encodeURIComponent((zh ? ZH : EN)[ch - 1])}` : page
}
