import { lang } from './i18n'
// Thin client for the Python backend (server/app.py).

/** a frame's automatic labels: each state's value (by state id), the labeler's flags and raw scores */
export interface LabelBrief {
  values: Record<string, unknown>
  flags: string[]
  scores?: Record<string, unknown>
}

/** Device sources (drivers/): where frames come from and where actions go. */
export interface DriverKind { label: string; caps: string[]; params: Record<string, string>; capture_modes: Record<string, string> }
export interface DriversInfo { kinds: Record<string, DriverKind>; current: { driver: string; params: Record<string, string> }; caps: Record<string, string> }

/** What a recorder plugin shows about one device while collecting. */
export interface RecorderLive {
  connected?: boolean; summary?: string | null
  meters?: { label: string; value: number | null; max: number | null; color?: string }[]
  info?: { label: string; value: string | number | null; wide?: boolean; warn?: boolean }[]
}

export interface LiveDevice {
  name: string; ok: boolean; detail: string; capturing: boolean; active: boolean
  extra?: Record<string, RecorderLive>
  samples: number; events: number; touches: number; failed_shots: number
  capture?: string | null; slow?: boolean; slow_shots?: number
}

export interface LiveStatus {
  running: boolean; stale: boolean; pid: number; session: string; session_dir: string
  started: number; updated: number; devices: LiveDevice[]; recorders?: Record<string, string>
}

export interface JobInfo {
  id: string; kind: string; title: string; status: 'running' | 'done' | 'failed' | 'stopped'
  returncode: number | null; started: number; ended: number | null; log: string[] | null
}

export interface SessionInfo {
  id: string; started: number | null; ended: number | null; minutes: number | null; samples: number; touches: number
  bytes: number; devices: { name: string; samples: number; touches: number; events: number; failed_shots: number }[]
}

export interface LabelSummary {
  labeler_version: number
  total: Record<string, number>
  by_session_device: Record<string, Record<string, number>>
}
export interface LabelVersion { version: string; updated: number; summary: LabelSummary }

export interface Overview {
  data_root: string; disk: { total: number; used: number; free: number }
  sessions: number; samples: number; touches: number; bytes: number
  recent_sessions: SessionInfo[]; collector: LiveStatus | null; labels: LabelVersion | null
  testset: { reviewed: number }; jobs: JobInfo[]
}

export interface SampleItem {
  id: string; t: number; trigger: string; frame: string; label: LabelBrief | null; reviewed: boolean
}

export interface SampleDetail {
  sample: Record<string, any>; frame: string; label: (LabelBrief & Record<string, any>) | null
  recorded: { title: string; rows: [string, string | number | null][] }[]
  review: Decision | null; prev: string | null; next: string | null; index: number; count: number
  events: Record<string, any>[]; touches: Record<string, any>[]
}

export type AnswerValue = number | string
export interface Decision {
  frame: string; session?: string; device?: string; id?: string
  answers: Record<string, AnswerValue | null>; note?: string; deleted?: boolean; reviewed_at?: number
  reviewer?: 'human' | 'claude'; unsure?: boolean; spot_check?: boolean
  skipped?: string[]          // questions this frame can't answer (asked no more)
  use?: 'train'               // a frame saved while scripts ran, answered as training data
}

export interface SaveReason { state: string; kind: 'low_conf' | 'disagree'; value?: unknown; conf?: number | null; rule?: unknown }
export interface ReviewItem {
  frame: string; session: string; device: string; id: string
  rule: Record<string, any> & { flags: string[] }; decision: Decision | null; needs_human: boolean
  origin?: 'testset' | 'uncertain' | 'flag'    // test set / saved while scripts ran (unsure, or "judged wrong")
  use?: 'test' | 'train'; reasons?: SaveReason[]; t?: number
  ask?: string[] | null      // the states this saved frame still asks (looked at again with the current model)
  auto_from?: 'label' | 'model'; conf?: Record<string, number>; urgent_states?: string[]
}

export interface StateStats {
  name: string; distribution: Record<string, number>; eval: Record<string, number>
  accuracy: number | null; coverage: number | null
}
export interface ReviewStats {
  reviewed: number; states: Record<string, StateStats>
  disagreements: { frame: string; field: string; human: any; rule: any }[]
  by_reviewer: Record<string, number>; needs_human: number
  claude_check: Record<string, any> & { differences: { frame: string; field: string; human: any; claude: any; kind: string }[] }
}

// ---------- state definitions (label schema) ----------
export type StateType = 'class' | 'ratio' | 'number' | 'gallery'
export type SourceKind = 'rule' | 'gallery' | 'manual' | string     // any other = a label source a plugin of the project adds
export interface ClassDef { value: AnswerValue; name: string; color: string; key?: string }
export interface RoiDef { id: string; name: string; box: [number, number, number, number] }
export interface StateDef {
  id: string; name: string; type: StateType; plugin?: string; description?: string
  unit?: string; min?: number; max?: number       // number states
  classes?: ClassDef[]; rois: RoiDef[]
  source: { kind: SourceKind; rule?: string; field?: string; params?: Record<string, any> }
  review?: { enabled: boolean; roi?: string; scale?: number }
  judge?: JudgeMode            // 判斷方式 while scripts run (a setting: no new version); default auto
  sources?: string[]           // only on these sources (ids / "#tag"; a setting); none = every source
}
export interface Schema { version: number; created: number; note: string; states: StateDef[]; settings_only?: boolean }   // settings_only: saved without a new version
export interface SchemaHistory { version: number; created: number; note: string; states: number }


export interface GalleryCluster { id: number; rep: string; ext: [number, number]; width: number; count: number; examples: string[] }
export interface GalleryEntry { file: string; name: string; width: number; created: number }
export interface GalleryInfo {
  id: string; name: string
  version: string | null; gallery: GalleryEntry[]; clusters: GalleryCluster[]; names: string[]
  counts: Record<string, number>; not_a_name: string; row: [number, number]
}

// ---------- generic rules ----------
export interface HsvRange { h: [number, number]; s: [number, number]; v: [number, number] }
export interface RulePreviewItem { frame: string; value: AnswerValue | null; ratio?: number | null; scores?: Record<string, number>; gated?: string; text?: string; min_score?: number | null; why?: string
  answer?: AnswerValue }     // a person's answer for this frame
/** thresholds that split the analysed frames (labeler/generic.py suggest_ratio) */
export type RatioSuggestion = { none: 'one_group' | 'few_frames' | 'answers_mixed' }
  | { low_max: number; high_min: number; basis: 'answers' | 'gap'; high: number; low: number; unsure: number; wrong: number; unsure_answers: number; none?: undefined }
/** what a 讀數字 rule finds on one frame: each character, what it is read as */
export interface GlyphsInfo { glyphs: { box: [number, number, number, number]; char: string | null; score: number }[]; text: string; value: number | null; taught: number }
export interface RuleTemplate { file: string; value: AnswerValue; frame: string; box: number[]; created: number }

// ---------- shadow mode ----------
export interface ShadowState {
  value: AnswerValue | number | null; conf?: number
  source?: 'model' | 'rule' | 'model+rule' | 'not_here'; rule?: string; score?: number | null      // rule: how the reference images / colours scored
  why?: string          // why the screen rule was used / joined in at this moment (runtime/arbiter.py)
  model_conf?: number   // model+rule: the model's own confidence (conf = after the rule agreed)
}
export interface NextStep { group: 'watch' | 'teach' | 'auto'; level: 'todo' | 'warn' | 'info' | 'ok'; title: string; detail: string; link: string; cta: string }
export interface NextSteps { steps: NextStep[]; todo: number }
export interface JudgeSource { source: 'model' | 'rule' | 'none'; reason: string; mode?: JudgeMode; only?: boolean; test?: 'pass' | 'partial' | 'fail' | null; test_reason?: string; acc?: number | null; holdout_acc?: number | null; mae?: number | null; rule?: string }
export interface UrgentCheck { min_acc: number; min_n: number; states: Record<string, { level: 'ok' | 'warn' | 'bad'; text: string; used_by: string[] }> }
export interface IncidentTrigger { key: string; script: string; script_name: string; rule: string; rule_name: string; text: string; reason: string; t: number; mode: string }
export interface IncidentEntry { t: number; kind: string; text: string; frame?: string; sid?: string; value?: unknown; level?: string; urgent?: boolean }
export interface Incident { id: string; device: string; start: number; end: number | null; status: string; triggers: IncidentTrigger[]; watch: string[]; entries: IncidentEntry[]
  clip?: [number, string][] }     // a frame a second from before the trigger to after it: [time, name]
export interface IncidentSummary {
  id: string; device: string; start: number; end: number | null; status: string; triggers: IncidentTrigger[]
  actions: number; urgent_actions: number; warnings: number; not_done: string[]; frame: string | null
}
export interface Schedule {
  id: string; name: string; enabled: boolean; at: string; days: number[]; window: number; devices: string[]
  sub: string; args: Record<string, ArgValue>; device_args?: Record<string, Record<string, ArgValue>>; pause_others: boolean; max_minutes: number
}
/** what the users changed on the operation panel, kept where it runs over the design */
export type ScheduleOverride = { enabled?: boolean; at?: string; devices?: string[] }
export interface ScheduleRunEntry { t: number; kind: string; text: string; frame?: string }
export interface ScheduleRun { id: string; schedule: string; schedule_name: string; device: string; start: number; end: number | null; result: string | null; message: string; entries: ScheduleRunEntry[] }
export interface PanelOption { label: string; value: unknown }
export interface PanelControl {
  id: string; label: string; help?: string; type: 'toggle' | 'time' | 'number' | 'multi' | 'single' | 'action'; scope?: 'global' | 'device'
  targets?: string[]                          // the emulators it is for (a per-emulator one) / a global button acts on
  devices?: string[]                          // the design: a per-emulator control only for these (ids / "#tag")
  unit?: string; min?: number; max?: number; value?: unknown; choices?: PanelOption[] | Record<string, PanelOption[]>; error?: string
  bind?: { kind: string; [k: string]: unknown }; options?: `list:${string}` | PanelOption[]; scale?: number
  chat?: string; chat_off?: boolean            // its name in a chat bot / only on the page
}
export interface PanelChatPreview {
  error: string | null; widgets: string[]
  commands: { name: string; control: string; block: string; type: string; scope: string }[]
}
export interface PanelDefinition {
  panel: { title: string; devices: string[]; pages?: PanelPage[]; blocks: PanelBlock[]; controls: PanelControl[]; sources?: PanelSourcePolicy }
  source_kinds?: { kind: string; label: string; category?: string; category_label?: string }[]
  binds: Record<string, string>; types: Record<string, string>; devices: string[]
  schedules: { id: string; name: string; sub: string; params: { name: string; label: string; type: string; item?: string | null; from_list?: string | null }[] }[]
  entries: { script: string; script_name: string; situation: string; situation_name: string; sub: string; params: { name: string; label: string; type: string; item?: string | null; from_list?: string | null }[] }[]
  buttons: { id: string; label: string; group?: string; device?: string; list?: string }[]
  lists: ListInfo[]
  settings: SettingDecl[]
  widgets: Record<string, string>; widget_defaults: Record<string, Record<string, unknown>>; modes: Record<string, string>
  main_scripts: { id: string; name: string }[]; runnable_subs: { id: string; name: string }[]
  acts: Record<string, string>
  scripts: { id: string; name: string; situations: { id: string; name: string }[] }[]
}
export interface QualityRates { n: number; conf: number | null; low: number | null; rule_n: number; dis: number | null }
export interface QualityInfo {
  model: string | null; hours: number; conf_low: number
  states: { id: string; name: string; recent: QualityRates; usual: QualityRates; hours: (QualityRates & { t: number })[]; devices: Record<string, QualityRates> }[]
  retrain: { run: string | null; started: number; days: number | null; answers: number; saved: number; unanswered: number; suggest: boolean; reasons: string[]; rule: string }
}
export interface NotifyChannel {
  id: string; name: string; type: string; enabled: boolean; config: Record<string, string>
  kinds: string[]; devices: string[]; quiet: { from: string; to: string } | null; image: boolean
}
export interface NotifyInfo {
  channels: NotifyChannel[]; merge_minutes: number; kinds: Record<string, string>; default_kinds: string[]
  status: Record<string, { last_ok?: number; last_error?: number; error?: string; sent?: number; failed?: number }>
  types: Record<string, { label: string; help: string; listens?: boolean; fields: { name: string; label: string; secret?: boolean; placeholder?: string }[] }>
}
export interface PanelWidget { kind: 'devices' | 'incidents' | 'deploy' | 'schedules' | 'log' | 'chat' | 'list'; [k: string]: unknown }
export interface ChatBot {
  id: string; name: string; type: string; label: string; enabled: boolean; state: string | null; error: string | null; invite: string | null
  paired: boolean; chat_name: string | null; allowed: { id: string; name?: string }[]; token_end: string
}
export interface PanelPage { id: string; title: string }
/** which sources the panel's users may scan for and pick (spec v6) */
export interface PanelSourcePolicy { kinds?: string[]; q?: string; help?: string; new_mode?: 'shadow' | 'live' }
export interface PanelSourceRow { kind: string; kind_label?: string; match: string; name: string; detail: string; warn?: string; bound?: string | null }
export interface PanelSources { can: boolean; help: string; kinds: { kind: string; label: string }[]
  items: { id: string; name: string; kind: string; kind_label: string; match: string; enabled: boolean }[] }
export interface PanelBlock { id: string; title: string; help?: string; toggle?: string; items: string[]; widget?: PanelWidget; data?: WidgetData; error?: string
  page?: string; width?: 'auto' | 'third' | 'narrow' | 'two_thirds' | 'wide' }   // which tab it is on (none = the first); its width on a wide screen (lib/panelLayout.ts)
export interface WidgetData {
  bots?: ChatBot[]; types?: { type: string; label: string; help: string }[]; setup?: boolean; pair?: boolean
  devices?: { device: string; now: string; tone: string; online: boolean; today: { name: string; text: string; code: string }[]; step: string | null; alerts: { t: number; text: string }[]; image: boolean }[]
  items?: { id: string; device: string; start: number; end: number | null; status: string; triggers: string[]; story: { t: number; text: string }[]; frame: string | null }[]
  rows?: { id: string; name: string; enabled?: boolean; at?: string; modes?: Record<string, string>; devices?: Record<string, { text: string; code: string }>; t?: number; device?: string; text?: string; level?: string }[]
  modes?: Record<string, string>; all_modes?: Record<string, string>
  // 清單 widget: per emulator ("*" = one shared list) its names and the last walk
  title?: string; per_device?: boolean; scan?: boolean; rename?: boolean; remove?: boolean
  by_device?: Record<string, PanelListDevice>
}
export interface PanelListDevice {
  scan: { t: number; total: number | null; new: string[]; missing: string[]; complete: boolean } | null
  busy: string | null
  items: { id: string; label: string; new: boolean; missing_since: number | null }[]
}
export interface PanelCard { device: string; online: boolean; now: string; tone: string; label?: string; today: { name: string; text: string; code: string }[]; alerts: { t: number; text: string }[]
  progress?: { name: string; paused: boolean; label?: string; i?: number; n?: number; wait_left?: number; wait_total?: number; eta?: number; say?: string | null } | null }
export interface PanelTodo {
  key: string; level: 'bad' | 'warn'; device: string | null; text: string; detail: string; t?: number
  go: { device?: string | null; block?: string | null }; ack?: boolean; frame?: string
}
export interface PanelInfo {
  pages?: PanelPage[]
  todo?: PanelTodo[]          // what to look at now, the most pressing first
  title: string; devices: string[]; controls: PanelControl[]; cards: PanelCard[]; blocks: PanelBlock[]; paused: boolean; running: boolean; paused_mode?: 'stop' | 'pause'
  asks?: AskItem[]
  history: { t: number; control: string; label: string; device?: string; old: unknown; new: unknown; action?: boolean; result?: Record<string, string> }[]
}
export type JudgeMode = 'auto' | 'model' | 'rule'
export interface JudgeInfo { run: string | null; run_name: string | null; running: boolean; states: Record<string, JudgeSource> }
export interface ShadowDecision {
  action: string; text: string; reason: string; tap: [number, number] | null
  script?: string; script_name?: string; mode?: string; rule?: string | null; rule_name?: string | null
  stable?: boolean; since?: number | null; exec?: string; done?: boolean; urgent?: boolean
  situation?: string; situation_name?: string; guard?: boolean; on_enter?: boolean
  sub?: string | null; args?: Record<string, unknown> | null; sub_steps?: string[] | null
}
/** a sub-script running on a device (it has control of that device) */
export interface ProcInfo {
  sub: string; sub_name: string; chain: { sub: string; step: number; steps: number }[]; now: string
  retry: string | null; loop?: string | null; paused?: boolean; cleaning: boolean; started: number; script?: string; script_name?: string; rule_name?: string
  result?: string | null; message?: string
}
export interface ShadowAct {
  device: string; kind: 'schedule' | 'sub' | 'situation' | 'stop' | 'pause' | 'resume'; id?: string; sub?: string; args?: Record<string, ArgValue>
  script?: string; situation?: string; mode?: 'abort' | 'pause' | 'stop'; if_busy?: 'ask' | 'interrupt' | 'queue'
}
export interface DeviceActions {
  device: string
  schedules: { id: string; name: string; enabled: boolean; at?: string; status?: { code: string; text: string } | null }[]
  scripts: { id: string; name: string; situations: { id: string; name: string; enter: boolean }[] }[]
}
export interface ShadowControl {
  max_per_min: number; max_strikes: number; unblock?: number; start_wait_s?: number
  manual_pause_s?: number; auto_save?: boolean; auto_save_per_hour?: number; live_view?: boolean; freeze_seconds?: number; blank_seconds?: number
}
export interface ShadowAlert { t: number; device: string; text: string; level: string }
export interface DeviceHealth { state: 'ok' | 'slow' | 'lost' | 'blank' | 'frozen'; text: string; fps: number; age: number | null; ms: number; since: number }
export interface ShadowDevice {
  name: string; window: string | null; health?: DeviceHealth; state: Record<string, ShadowState> | null; decisions: ShadowDecision[]
  proc?: ProcInfo | null; taps_last_min?: number
  held?: string | null                                    // a guard rule is holding the other scripts
  situations?: Record<string, { id: string; name: string; since: number; count: number }>
  manual?: { watched: boolean; paused: boolean; resume_in: number; last: number | null } | null     // null = pausing is off
  hold?: Hold | null                                     // 停下來 / 暫停 (its own or all's): nothing acts until 繼續
  cause_now?: boolean | null                             // what stopped it (a rule) is still so now (null: cannot tell)
  start_wait?: number                                     // seconds of the start check still to go (1e9: no healthy picture yet)
}
/** 停下來 / 暫停: from a person (by = who), or a rule / a script that stopped the device (why, cause; again = it
 *  stopped again this many seconds after a 繼續, the cause is still there) */
export interface Hold { mode: 'stop' | 'pause'; by: string; t: number; why?: string; cause?: { script: string; rule: string | null }; again?: number }
export interface ShadowStatus {
  running?: boolean; started?: number; updated?: number; model?: string; interval?: number; ticks?: number
  tick_ms?: number; model_ms?: number; model_backend?: string; decisions?: Record<string, number>; devices?: ShadowDevice[]
  control?: ShadowControl; alerts?: ShadowAlert[]; saved_last_hour?: number; hold_all?: Hold | null
  incidents_open?: { id: string; device: string; start: number; triggers: string[]; resolved: number | null }[]
  vars?: { defs: VarDef[]; global: Record<string, number>; device: Record<string, Record<string, number>> }; blocked?: { device: string; script: string; rule: string; reason: string; since?: number; again?: number | null }[]
}
export interface ShadowLog {
  t: number; device: string; action: string; text: string; reason: string; tap: number[] | null; state: Record<string, any>
  script?: string; script_name?: string; mode?: string; rule_name?: string | null
  executed?: boolean; image?: string | null; flow_steps?: string[] | null; level?: string
}
export interface ShadowFlag {
  t: number; device: string; frame: string; session: string; id: string; pred: Record<string, any>
  conf: Record<string, number>; decision?: ShadowDecision; decisions?: ShadowDecision[]; note: string; answered: Record<string, any> | null
}

// ---------- scripts (no-code automation) ----------
/** a condition; kind defaults to "state" (see automation/conds.py) */
/** where a value comes from when the script runs (script spec: automation/values.py) */
export type ValueRef = { param: string } | { setting: string } | { var: string } | { state: string } | { sum: NumVal[] }
export type NumVal = number | ValueRef
export const isRef = (v: unknown): v is ValueRef => !!v && typeof v === 'object' && !Array.isArray(v)
  && Object.keys(v as object).length === 1 && ['param', 'setting', 'var', 'state', 'sum'].includes(Object.keys(v as object)[0])
export interface ScriptCond {
  kind?: 'state' | 'became' | 'count' | 'change' | 'time' | 'always' | 'var' | 'elapsed' | 'device' | 'visible' | 'compare'
  target?: ScriptPoint; left?: NumVal; right?: NumVal
  state?: string; op?: string; value?: AnswerValue | NumVal; for?: number; min_conf?: number
  within?: number; times?: NumVal; dir?: 'drop' | 'rise'; amount?: NumVal
  from?: string; to?: string; days?: number[]; var?: string; device?: string
}
export interface ReplayTick {
  t: number; frame: string; state: Record<string, [unknown, number | null, string | undefined]>
  situations: Record<string, string>; held: string | null
  decisions: { script: string; script_name: string; situation_name?: string; action: string; text: string; reason: string; exec?: string; done?: boolean; rule_name?: string; guard?: boolean; on_enter?: boolean }[]
  events: { t: number; kind: 'input' | 'call' | 'alert' | 'info'; text: string }[]
}
/** script tests (automation/tests.py) */
export interface TestExpect { kind: 'situation' | 'call' | 'input' | 'output' | 'stop' | 'alert'; output?: string; when: 'end' | 'ever' | 'never'; script?: string; situation?: string
  sub?: string; rule?: string; text?: string; min?: number | null; max?: number | null; within?: [number, number] | null }
export interface TestCase { id: string; name: string; description?: string; session: string; device: string; start: number; minutes: number
  sub_result: 'success' | 'fail'; sub_results?: Record<string, 'success' | 'fail'>; expect: TestExpect[] }
export interface TestResult { run_at: number; status: 'pass' | 'fail' | 'error'; checks: { ok: boolean; text: string; detail: string }[]
  frames?: number; seconds?: number; error?: string; replay?: string; model?: string }
export interface TestsInfo {
  tests: (TestCase & { expect_text: string[]; last?: TestResult })[]; job: JobInfo | null; kinds: Record<string, string>
  scripts: { id: string; name: string; situations: { id: string; name: string }[]; rules: { id: string; name: string }[] }[]
  subs: { id: string; name: string }[]
}
export interface ReplayResult {
  id: string; session: string; device: string; sub_result: string; draft: boolean; created: number
  summary: { frames: number; from: number; to: number; inputs: number; calls: number; alerts: number; infos: number; switches: number }
  ticks: ReplayTick[]
}
export interface TimelineRow {
  t: number; action: string; executed?: boolean; script_name?: string; rule_name?: string; text?: string; reason?: string
  level?: string; mode?: string; var?: string; old?: unknown; new?: unknown
}
export interface VarDef { name: string; label?: string; scope: 'device' | 'global'; reset: 'daily' | 'never'; initial?: number }
export interface ScriptPoint { x?: number; y?: number; param?: string; button?: string }
/** a named tap position of the button library; "find" = look for its picture first */
export interface LibButton {
  id: string; label: string; x: number; y: number; find?: boolean; box?: number[]; search?: number; min_score?: number; updated?: number
  feature?: 'gray' | 'minch' | 'text'; group?: string; device?: string; list?: string
}
export interface TemplateInfo { id: string; kind: 'script' | 'sub' | 'guard_rules'; name: string; description: string }
export type ArgItem = ScriptPoint | number | string
export type ArgValue = ArgItem | ArgItem[] | { param: string } | { setting: string }
/** a parameter the design opens to its users (使用者設定): declared here, the value is chosen where it runs */
export interface ListInfo { id: string; title: string; per_device: boolean; open_sub?: string | null; ready_text?: string | null }
export interface SettingDecl {
  id: string; label: string; description?: string
  type: 'number' | 'text' | 'bool' | 'time' | 'point' | 'list'; item?: 'point' | 'number' | 'text'
  pick_from?: string                      // "list:<id>": the value must be one of that list's names (the device's if per device)
  scope: 'device' | 'shared'; default?: unknown; device_default?: Record<string, unknown>
  min?: number; max?: number; min_items?: number; max_items?: number
}
export type Choice = { label: string; value: unknown }
export interface SettingsInfo {
  settings: SettingDecl[]; types: Record<string, string>; items: Record<string, string>; scopes: Record<string, string>
  used_by: Record<string, string[]>; current: Record<string, Record<string, unknown>>; chosen: Record<string, string[]>
  devices: string[]; choices: Record<string, Record<string, Choice[] | null>>; lists: ListInfo[]
}
export interface ScriptAction {
  type: string; target?: ScriptPoint; text?: string; sub?: string; args?: Record<string, ArgValue>
  on_success?: string; on_fail?: string      // call: situation id (or "stop") after the sub-script
  situation?: string                         // goto
  var?: string; mode?: string; value?: NumVal  // set_var (value: also output)
  output?: string; command?: string            // output
}
export interface Situation {
  id: string; name: string; rules: ScriptRule[]; on_enter?: SubStep[] | null; max_seconds?: number | null; on_timeout?: string
}
/** one step of a sub-script; blocks (if / retry / repeat_until) hold nested step lists */
export interface SubStep {
  say?: string; say_fail?: string            // for the people running it, in plain words: what it is doing / what went wrong
  type: string; label?: string; target?: ScriptPoint; ms?: NumVal; from?: ScriptPoint; to?: ScriptPoint
  seconds?: NumVal; when?: ScriptCond[][]; timeout?: NumVal; on_timeout?: string; text?: string
  then?: SubStep[]; elif?: { when: ScriptCond[][]; then: SubStep[] }[]; else?: SubStep[]; steps?: SubStep[]; times?: NumVal; delay?: NumVal; max_times?: NumVal; max_seconds?: NumVal
  sub?: string; args?: Record<string, ArgValue>; on_fail?: string; fail_goto?: string
  situation?: string                         // goto (切換情境)
  after?: { seconds?: NumVal; until?: ScriptCond[][]; timeout?: NumVal; on_timeout?: string }   // input steps: wait after
  var?: string; mode?: string; value?: NumVal
  list?: string; as?: string; as_label?: string; on_item_fail?: string; max_swipes?: NumVal; settle?: NumVal; package?: string
  output?: string; command?: string
  options?: { label: string; then: SubStep[] }[]; default?: number      // ask (問使用者)
}
export interface SourceRef { kind: string; what: string; text: string }
export interface SourceNative {
  kind: string; kind_label: string; category_label?: string; match: string; detail: string; ok?: boolean; size: number[] | null; size_warn: string | null
  seen?: number; ignored?: boolean; bound?: string | null; opts?: Record<string, string> | null; per_source?: boolean
  category?: string; same_as?: string | null; suggest?: { kind: string; label: string; category_label: string } | null
}
export interface SourceItem {
  id: string; kind: string; match: string; name: string; enabled: boolean; added: number; label: string; kind_label: string
  present: boolean; detail: string; size: number[] | null; size_warn: string | null; watching: boolean; window: boolean; caps: string[]
  refs: SourceRef[]; hand: SourceHand; hand_text: string; used_as_hand_by: string[]
  params?: Record<string, string>; per_source: Record<string, SourceParam>; tags?: string[]
  health?: DeviceHealth | null
}
export interface SourceParam { label: string; type: 'select' | 'text' | 'bool'; options?: Record<string, string>; help?: string }
export interface SourceKindInfo {
  label: string; category: string; category_label: string; preset: string; note: string; caps: string[]
  params: Record<string, SourceParam>; defaults: Record<string, unknown>; on: boolean; params_set: Record<string, unknown>
  per_source: Record<string, SourceParam>; in_use: number; manual?: boolean; has_hand?: boolean
}
export interface SourceHand { to: 'self' | 'source' | 'output' | 'none'; id?: string }
export interface SourceView {
  kinds: Record<string, SourceKindInfo>
  items: SourceItem[]; new: SourceNative[]; missing: string[]; hands: Record<string, string>; outputs: { id: string; name: string }[]
}
export interface AskItem {
  id: string; device: string; text: string; options: string[]; created: number; expires: number; default: number | null; script_name?: string
}
export interface SubParam { name: string; from_list?: string; label?: string; type: 'point' | 'number' | 'text' | 'list'; item?: 'point' | 'number' | 'text'; default?: ArgValue }
export interface SubScript {
  id: string; name: string; description?: string; params?: SubParam[]; steps: SubStep[]; cleanup?: SubStep[]; timeout?: number
  version?: number; created?: number; note?: string; outline?: string[]
  say?: string; say_fail?: string            // for the people running it: what it does / what to say when it fails
}
export interface ScriptRule {
  id: string; name: string; enabled: boolean; urgent?: boolean; when: ScriptCond[][]; do: SubStep[]
  cooldown?: number; max_per_hour?: number; max_per_day?: number
}
export interface Script {
  id: string; name: string; description?: string; enabled: boolean; devices: Record<string, string>
  situations: Situation[]; initial: string; otherwise?: ScriptAction; version?: number; created?: number; note?: string
  settings_only?: boolean      // the last save changed only settings (where it runs, limits ...): no new version
}
/** how the sub-script library is arranged: groups (folders) and the order inside them */
export interface SubLayout { groups: { id: string; name: string }[]; of: Record<string, string>; order: string[] }
export interface ScriptsInfo {
  scripts: Script[]
  modes: Record<string, string>; actions: Record<string, string>; ops: Record<string, string>
  order: string[]; subs: SubScript[]; used_by: Record<string, string[]>; sub_layout: SubLayout; settings: SettingDecl[]
  lists: ListInfo[]
  step_types: Record<string, string>; param_types: Record<string, string>; cleanup_steps: string[]
  step_groups: [string, string[]][]; after_steps: string[]; on_fail: Record<string, string>
  cond_kinds: Record<string, string>; variables: VarDef[]; buttons: LibButton[]; templates: TemplateInfo[]
  var_modes: Record<string, string>; var_scopes: Record<string, string>; var_resets: Record<string, string>
  outputs: { id: string; name: string }[]
}
/** a bot channel that takes commands (notify/commands.py) */
export interface BotInfo { state: { state: string; error: string | null; since: number } | null; allowed: { id: string; name?: string }[]; chat_name?: string; paired: boolean; invite: string | null }
/** sharing sub-scripts (automation/share.py) */
export interface ShareBundle { kind: string; format: number; from?: string; subs: SubScript[]; buttons: Record<string, unknown>; states: Record<string, unknown> }
export interface ShareAnalysis {
  from?: string; exported?: number; screen?: [number, number]; here_screen: [number, number]; missing_subs: string[]
  subs: { id: string; name: string; exists: boolean; here_name?: string }[]
  buttons: { id: string; label: string; find: boolean; has_image: boolean; match: string; exists: boolean; can_create: boolean }[]
  states: { id: string; name: string; match: string }[]; lists: { id: string; title: string; match: string }[]
  outputs: { id: string; name: string; match: string }[]
  variables: { name: string; label?: string; exists: boolean }[]; settings: { id: string; label?: string; exists: boolean }[]
}
/** where scripts send things besides the screen (automation/outputs.py) */
export interface OutputDef { id: string; name: string; type: string; url?: string; method?: string; headers?: Record<string, string>; [k: string]: unknown }
export interface OutputsInfo { outputs: OutputDef[]; types: Record<string, { label: string; fields: Record<string, string> }> }
export interface ScriptTestResult { updated: number; running: boolean; results: (ShadowDecision & { device: string; state: Record<string, ShadowState> | null })[] }

// ---------- training ----------
export interface TrainConfig {
  name: string; epochs: number; width: number; height: number; batch: number; lr: number
  pretrained: boolean; holdout: string[]; neighbor_seconds: number; augment: boolean; seed: number; relabel: boolean
}
export interface LabelsStatus { version: string | null; built: number | null; stale: boolean; reasons: string[]; new_sessions?: string[] }
export interface HeadSummary {
  id: string; name: string; kind: 'class' | 'ratio'; classes?: string[]; class_names?: string[]
  splits: Record<string, Record<string, number>>
}
export interface DatasetSummary {
  labels_version: string; schema_version: number
  splits: Record<string, { frames: number; devices: Record<string, number> }>
  heads: HeadSummary[]; all_devices?: string[]; unlabeled_sessions?: string[]
  labels_status?: LabelsStatus; labeling?: JobInfo | null
}
export interface RunStatus {
  state?: 'loading' | 'training' | 'evaluating' | 'done' | 'failed' | 'stopped'; message?: string
  epoch?: number; epochs?: number; step?: number; steps?: number; best_epoch?: number
  img_per_s?: number; epoch_seconds?: number; started?: number; updated?: number
  phase?: string; phase_name?: string; done?: number | null; total?: number | null
  eta_phase?: number | null; eta_total?: number | null
}
export interface RunBrief {
  id: string; config: TrainConfig | null; created: number | null; device: string | null
  splits: Record<string, number>; labels_version: string | null; schema_version: number | null; status: RunStatus
  result: Record<string, { model_acc: number | null; rule_acc: number | null; test_mae: number | null; holdout_acc: number | null }> | null
}
export interface EpochMetrics {
  epoch: number; lr: number; seconds: number; best: boolean
  train_loss: Record<string, number>; val: Record<string, number | null>; test: Record<string, number | null>
}
export interface HeadEval {
  name: string; kind: 'class' | 'ratio'; n: number; classes?: string[]; class_names?: string[]
  model_acc?: number | null; by_group?: Record<string, { acc: number | null; n: number }>; confusion?: number[][]
  rule?: { correct?: number; wrong?: number; abstain_ok?: number; abstain_missed?: number; acc_when_answered: number | null; coverage: number | null; acc_overall: number | null }
  test_mae?: number | null
}
export interface ModelTest { result: 'pass' | 'partial' | 'fail'; reason: string }
export interface ProgressStep { key: 'define' | 'judge' | 'test' | 'model'; name: string; status: 'ok' | 'partial' | 'todo' | 'na'; text: string; link: string }
export interface StateProgress { steps: ProgressStep[]; current: number | null; source?: 'model' | 'rule' | 'none'; source_reason?: string }
export interface ProgressInfo { run: string | null; run_name: string | null; criteria: { min_answers: number; min_per_class: number; holdout_min: number }; states: Record<string, StateProgress> }
export interface RunDetail extends RunBrief {
  tests?: Record<string, ModelTest>
  dataset: DatasetSummary | null; metrics: EpochMetrics[]
  heads: { id: string; name: string; kind: 'class' | 'ratio'; classes?: (string | number)[]; class_names?: string[] }[] | null
  eval: { run: string; best_epoch: number; test_frames: number; holdout: string[]; heads: Record<string, HeadEval>
    mistakes: { frame: string; device: string; state: string; answer: any; pred: any; conf: number; rule: any }[] } | null
}

/** an installed pack (<data>/packs/<id>/) */
export interface PackItem {
  id: string; name: string; version: string; active: boolean; workspace: boolean
  problems: { level: 'error' | 'warn'; text: string }[]
}
export interface PacksInfo { layout: boolean; packs: PackItem[]; active?: string; edition: 'studio' | 'runtime'; platform: string }
export interface PackDone { messages: string[]; restart: boolean; id?: string; version?: string; old?: string | null }
/** before exporting the running pack: what it is, the last release and what changed since, what to look at */
export interface PackExportCheck {
  pack: { id: string; name: string; version: string; description?: string; license?: string; homepage?: string }
  next: string; last: { version: string; file: string } | null; files: number; out: string
  checks: { level: 'error' | 'warn' | 'ok' | 'info'; text: string }[]
  changes: { added: string[]; removed: string[]; changed: string[] } | null
}
/** project.json as the pages see it: what it is called, its coordinate space and words */
/** where the disk goes (server/storage.py); bytes */
export interface Storage {
  sizes: { recordings: number; records: number; models: number; answers: number; other: number }; total: number
  per_day: { recordings: number; records: number }; growing: number; free: number; disk_total: number
  days_left: number | null; keep_days: number; record_days: number; t: number
  keep: Record<KeepKind, number>; min_free_gb: number; when_full: 'stop' | 'cycle'
}
export type KeepKind = 'actions' | 'incidents' | 'schedules' | 'logs'
/** what cleaning the run's records would delete / deleted */
export interface CleanResult { files: number; bytes: number; kinds: Partial<Record<KeepKind, { files: number; bytes: number }>> }
export interface CleanRecord { t: number; by: 'runner' | 'user' | 'room'; what: 'records' | 'recordings' | 'models' | 'stopped'; files: number; bytes: number
  kinds?: CleanResult['kinds']; sessions?: string[]; runs?: string[]; why?: string }
/** this computer's storage settings: how new recordings keep their frames */
export interface StorageSettings { record_format: 'png' | 'jpg'; jpeg_quality: number; keep: Record<KeepKind, number>; keep_models: number; min_free_gb: number; when_full: 'stop' | 'cycle' }
export type AiLevel = 'read' | 'design' | 'run'
/** a token for one AI client over the network (only its hash is kept) */
export interface AiToken { id: string; name: string; level: AiLevel; created: number; last_used: number | null; revoked: number | null }
/** one change an AI made (server/ai_api.py) */
export interface AiLogEntry { id: string; t: number; tool: string; target: string; reason: string; client: string; before?: unknown; after?: unknown }
/** what an AI (over MCP) asked a person to decide (server/ai_api.py) */
export interface AiRequest { id: string; t: number; kind: 'live'; script: string; script_name: string; device: string; device_name: string
  reason: string; status: 'open' | 'approved' | 'declined'; answered?: number }
/** moving the work folder (project/relocate.py) */
export interface LocationCheck { ok: boolean; problems: string[]; from: string | null; to: string | null; bytes: number; files: number; free: number | null }
export interface StorageLocation {
  current: string | null; pack_work: string; movable: boolean; running_from: string; restart_needed: boolean; old_exists: boolean
  move: { phase?: 'copy' | 'check' | 'done' | 'failed' | 'deleting' | 'deleted'; from?: string; to?: string; files?: number; files_done?: number
    bytes?: number; bytes_done?: number; error?: string | null; t?: number }
  job: JobInfo | null
}
export interface ProjectSettings { id: string; name: string; description: string; screen: { width: number; height: number }; words: Record<string, string> }
export interface PackExported { file: string; size: number; messages: string[] }

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json', 'X-Lang': lang } : { 'X-Lang': lang },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (r.status === 401 && !url.startsWith('/api/auth/')) window.dispatchEvent(new Event('lm-login-needed'))
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try { msg = (await r.json()).detail ?? msg } catch { /* not json */ }
    throw new Error(msg)
  }
  return r.json()
}

const qs = (p: Record<string, string | number | undefined>) =>
  new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)])).toString()

export const api = {
  language: () => req<{ machine: string; available: string[]; names: Record<string, string> }>('GET', '/api/language'),
  languageSet: (machine: string) => req<{ machine: string; available: string[]; names: Record<string, string> }>('POST', '/api/language', { machine }),
  overview: () => req<Overview>('GET', '/api/overview'),
  projectGet: () => req<ProjectSettings>('GET', '/api/project'),
  gettingStarted: () => req<{ done: Record<string, boolean> }>('GET', '/api/getting_started'),
  storage: (fresh = false) => req<Storage>('GET', `/api/storage${fresh ? '?fresh=true' : ''}`),
  storageClean: () => req<CleanResult & { storage: Storage }>('POST', '/api/storage/clean'),
  storageCleanPreview: () => req<CleanResult>('GET', '/api/storage/clean'),
  storageHistory: () => req<{ items: CleanRecord[] }>('GET', '/api/storage/history'),
  storageModelsPreview: () => req<{ runs: string[]; bytes: number }>('GET', '/api/storage/models'),
  storageModelsClean: () => req<{ runs: string[]; bytes: number }>('POST', '/api/storage/models'),
  storageLocation: () => req<StorageLocation>('GET', '/api/storage/location'),
  aiRequests: () => req<{ items: AiRequest[] }>('GET', '/api/ai/requests'),
  aiConnect: () => req<{ folder: string; python: string; port: number; lan_mcp: string | null; local_mcp: string; tokens: number }>('GET', '/api/ai/connect'),
  aiTokens: () => req<{ items: AiToken[] }>('GET', '/api/ai/tokens'),
  aiTokenNew: (name: string, level: AiLevel) => req<AiToken & { token: string }>('POST', '/api/ai/tokens', { name, level }),
  aiTokenRevoke: (id: string) => req<AiToken>('POST', `/api/ai/tokens/${encodeURIComponent(id)}/revoke`),
  aiLog: () => req<{ items: AiLogEntry[] }>('GET', '/api/ai/log?limit=100'),
  aiUndo: (id: string) => req<{ done: string }>('POST', `/api/ai/undo/${encodeURIComponent(id)}`),
  aiRequestAnswer: (id: string, approve: boolean) => req<AiRequest>('POST', `/api/ai/requests/${encodeURIComponent(id)}/answer`, { approve }),
  storageSettings: () => req<StorageSettings>('GET', '/api/storage/settings'),
  storageSettingsSave: (b: Partial<StorageSettings>) => req<StorageSettings>('POST', '/api/storage/settings', b),
  storageLocationCheck: (to: string) => req<LocationCheck>('POST', '/api/storage/location/check', { to }),
  storageLocationMove: (to: string) => req<{ job: JobInfo; stopped_runner: boolean }>('POST', '/api/storage/location/move', { to }),
  storageLocationDeleteOld: () => req<{ job: JobInfo }>('POST', '/api/storage/location/delete_old'),
  projectSettingsSave: (b: { name: string; description: string; words: Record<string, string> }) => req<ProjectSettings>('POST', '/api/project/settings', b),
  packs: () => req<PacksInfo>('GET', '/api/packs'),
  /** the zip itself is the body */
  packInstall: async (file: File, o: { force?: boolean; activate?: boolean }) => {
    const r = await fetch(`/api/packs/install?${qs({ force: o.force ? 1 : 0, activate: o.activate ? 1 : 0 })}`,
      { method: 'POST', headers: { 'Content-Type': 'application/zip', 'X-Lang': lang }, body: file })
    if (!r.ok) {
      let msg = `${r.status} ${r.statusText}`
      try { msg = (await r.json()).detail ?? msg } catch { /* not json */ }
      throw new Error(msg)
    }
    return r.json() as Promise<PackDone>
  },
  packUse: (id: string) => req<PackDone>('POST', '/api/packs/use', { id }),
  packExportCheck: (model: boolean) => req<PackExportCheck>('GET', `/api/packs/export?${qs({ model: model ? 1 : 0 })}`),
  packExport: (b: { version: string; name: string; description: string; model: boolean }) => req<PackExported>('POST', '/api/packs/export', b),
  restart: () => req<{ ok: boolean }>('POST', '/api/system/restart'),
  nextSteps: () => req<NextSteps>('GET', '/api/next_steps'),
  devices: () => req<{ name: string; ok: boolean; detail: string; size: string; replay?: boolean }[]>('GET', '/api/devices'),
  drivers: () => req<DriversInfo>('GET', '/api/drivers'),
  driversSet: (b: { driver: string; params: Record<string, string> }) => req<DriversInfo>('PUT', '/api/drivers', b),
  collector: () => req<{ live: LiveStatus | null; job: JobInfo | null; prefix_names: Record<string, string[]> }>('GET', '/api/collector'),
  collectorStart: (b: { interval: number; minutes: number; only: string[]; touch: boolean; label_after: boolean; capture: string }) => req<JobInfo>('POST', '/api/collector/start', b),
  collectorStop: () => req<{ stopped: boolean }>('POST', '/api/collector/stop'),
  jobs: () => req<JobInfo[]>('GET', '/api/jobs'),
  job: (id: string) => req<JobInfo>('GET', `/api/jobs/${id}`),
  sessions: () => req<SessionInfo[]>('GET', '/api/sessions'),
  samples: (p: { session: string; device: string; offset?: number; limit?: number; state?: string; value?: string; flag?: string; trigger?: string; reviewed?: string }) =>
    req<{ total: number; offset: number; items: SampleItem[] }>('GET', `/api/samples?${qs(p)}`),
  find: (q: string) => req<{ session: string; device: string; id: string; t: number }[]>('GET', `/api/find?${qs({ q })}`),
  sample: (session: string, device: string, id: string) => req<SampleDetail>('GET', `/api/sample?${qs({ session, device, id })}`),
  labels: () => req<LabelVersion[]>('GET', '/api/labels'),
  labelsRun: (sessions: string[] = []) => req<JobInfo>('POST', '/api/labels/run', { sessions }),
  reviewQueue: () => req<{ version: string; total: number; done: number; needs_human: number; runtime_todo: number; items: ReviewItem[] }>('GET', '/api/review/queue'),
  reviewDecide: (d: Decision) => req<Decision>('POST', '/api/review/decision', d),
  reviewPriorities: () => req<{ put_aside: number; tidy: { current: boolean; t: number | null; learned: number; dupes: number; user: number; job: JobInfo | null }; states: { state: string; name: string; level: 'suggest' | 'ok' | 'later'; level_text: string; why: string; answers: number; unsure_todo: number; todo: number; low_conf: number; median_conf: number | null; need: number | null; stuck: number; best: string[] }[]; round: number; model: string | null; since: number | null }>('GET', '/api/review/priorities'),
  reviewPutAside: (restore = false) => req<{ put_aside: number; job: JobInfo | null }>('POST', '/api/review/put_aside', { restore }),
  reviewAnswerOne: (b: { frame: string; state: string; value: AnswerValue | null }) => req<unknown>('POST', '/api/review/answer_one', b),
  reviewAnswers: (state: string) => req<{ answers: Record<string, AnswerValue>; counts: Record<string, number> }>('GET', `/api/review/answers/${encodeURIComponent(state)}`),
  imageWarm: (paths: string[]) => req<{ queued: number }>('POST', '/api/image/warm', { paths }),
  reviewAddQuestions: (state: string, n = 30, session?: string, device?: string) => req<{ added: number; by_answer: Record<string, number>; available: Record<string, number> }>('POST', '/api/review/add_questions', { state, n, session, device }),
  statesProgress: () => req<ProgressInfo>('GET', '/api/states/progress'),
  reviewStats: () => req<ReviewStats>('GET', '/api/review/stats'),
  states: () => req<{ schema: Schema; history: SchemaHistory[] }>('GET', '/api/states'),
  statesVersion: (v: number) => req<Schema>('GET', `/api/states/v/${v}`),
  statesSave: (states: StateDef[], note: string) => req<Schema>('POST', '/api/states', { states, note }),
  schedules: () => req<{ items: Schedule[]; status: Record<string, Record<string, { code: string; text: string; online?: boolean; run?: string | null }>>; running: boolean; day_start: string; overrides: Record<string, ScheduleOverride> }>('GET', '/api/schedules'),
  scheduleOverrideClear: (id: string, field?: string) => req<{ overrides: Record<string, ScheduleOverride> }>('POST', '/api/schedules/override/clear', { id, field }),
  schedulesSave: (items: Schedule[], day_start?: string) => req<{ items: Schedule[] }>('POST', '/api/schedules', { items, day_start }),
  scheduleRequest: (b: { action: 'run_now' | 'reset'; id: string; device?: string }) => req<{ queued: boolean }>('POST', '/api/schedules/request', b),
  scheduleRuns: (limit = 200) => req<{ items: (Omit<ScheduleRun, 'entries'> & { steps: number })[] }>('GET', `/api/schedules/runs?limit=${limit}`),
  scheduleRun: (id: string) => req<ScheduleRun>('GET', `/api/schedules/runs/${encodeURIComponent(id)}`),
  scheduleRunFrameUrl: (id: string, name: string) => `/api/schedules/runs/${encodeURIComponent(id)}/frame/${encodeURIComponent(name)}`,
  authMe: () => req<{ role: 'admin' | 'user' | null; local: boolean; configured: { user: boolean; admin: boolean }; lan: string | null }>('GET', '/api/auth/me'),
  authLogin: (pin: string) => req<{ role: string }>('POST', '/api/auth/login', { pin }),
  authLogout: () => req<{ ok: boolean }>('POST', '/api/auth/logout'),
  authPins: (b: { user_pin?: string; admin_pin?: string }) => req<{ user: boolean; admin: boolean }>('POST', '/api/auth/pins', b),
  panel: () => req<PanelInfo>('GET', '/api/panel'),
  panelSet: (b: { control: string; device?: string; value: unknown }) => req<{ old: unknown; new: unknown }>('POST', '/api/panel/set', b),
  panelDefinition: () => req<PanelDefinition>('GET', '/api/panel/definition'),
  panelDefinitionSave: (panel: PanelDefinition['panel']) => req<{ ok: boolean }>('POST', '/api/panel/definition', { panel }),
  panelChatPreview: (panel: PanelDefinition['panel']) => req<PanelChatPreview>('POST', '/api/panel/chat_preview', { panel }),
  notifyHelp: () => req<{ text: string }>('GET', '/api/notify/help'),
  asks: () => req<{ items: AskItem[] }>('GET', '/api/asks'),
  sourceNames: () => req<{ names: Record<string, string>; enabled: string[]; hands: Record<string, string>; tags: Record<string, string[]> }>('GET', '/api/sources/names'),
  sources: () => req<SourceView>('GET', '/api/sources'),
  sourceScan: (kinds: string[], q: string) => req<{ found: SourceNative[]; errors: Record<string, string> }>('POST', '/api/sources/scan', { kinds, q }),
  sourceAdd: (b: { kind: string; match: string; id?: string; name?: string; params?: Record<string, string> }) => req<{ id: string; trial?: string[] }>('POST', '/api/sources/add', b),
  sourceUpdate: (b: { id: string; name?: string; enabled?: boolean; match?: string; kind?: string; hand?: SourceHand; params?: Record<string, string>; tags?: string[] }) => req<SourceView & { now_live?: string[] }>('POST', '/api/sources/update', b),
  sourceRemove: (id: string, force = false) => req<{ refs: SourceRef[]; removed: boolean }>('POST', '/api/sources/remove', { id, force }),
  sourceKind: (kind: string, on: boolean, params: Record<string, unknown>) => req<SourceView>('POST', '/api/sources/kind', { kind, on, params }),
  sourceIgnore: (kind: string, match: string, ignore = true) => req<{ ok: boolean }>('POST', '/api/sources/ignore', { kind, match, ignore }),
  answer: (id: string, option: number) => req<{ message: string }>('POST', '/api/panel/answer', { id, option }),
  panelAct: (b: { control: string; device?: string; if_busy?: 'ask' | 'interrupt' | 'queue'; resume?: boolean }) =>
    req<{ busy: Record<string, { name?: string; loop?: string | null; now?: string }>; done: Record<string, string>; errors?: Record<string, string> }>('POST', '/api/panel/act', b),
  panelDeploy: (b: { block: string; script: string; device: string; mode: string }) => req<{ old: string; new: string }>('POST', '/api/panel/deploy', b),
  panelSources: () => req<PanelSources>('GET', '/api/panel/sources'),
  panelSourcesScan: () => req<{ found: PanelSourceRow[]; errors: Record<string, string> }>('POST', '/api/panel/sources/scan'),
  panelSourcesUse: (b: { kind: string; match: string; use: boolean; name?: string }) => req<{ ok: boolean; id?: string }>('POST', '/api/panel/sources/use', b),
  panelTodoAck: (keys: string[]) => req<{ ok: boolean }>('POST', '/api/panel/todo/ack', { keys }),
  panelListItem: (block: string, b: { device: string; id: string; action: 'rename' | 'keep' | 'remove'; label?: string }) =>
    req<{ ok: boolean }>('POST', `/api/panel/list/${encodeURIComponent(block)}/item`, b),
  panelListScan: (block: string, device: string, if_busy: 'ask' | 'interrupt' | 'queue') =>
    req<{ busy: Record<string, { name?: string; loop?: string | null; now?: string }>; done: Record<string, string>; errors?: Record<string, string> }>('POST', `/api/panel/list/${encodeURIComponent(block)}/scan`, { device, if_busy }),
  panelChatSave: (b: { id?: string; type?: string; name?: string; token?: string }) => req<{ id: string }>('POST', '/api/panel/chat/save', b),
  panelChatRemove: (id: string) => req<{ ok: boolean }>('POST', '/api/panel/chat/remove', { id }),
  panelChatPair: (id: string) => req<{ code: string; seconds: number }>('POST', '/api/panel/chat/pair', { id }),
  panelChatUnpair: (id: string, user: string) => req<{ ok: boolean }>('POST', '/api/panel/chat/unpair', { id, user }),
  quality: (hours = 24) => req<QualityInfo>('GET', `/api/quality?hours=${hours}`),
  notify: () => req<NotifyInfo>('GET', '/api/notify'),
  notifySave: (b: { channels: NotifyChannel[]; merge_minutes: number }) => req<NotifyInfo>('POST', '/api/notify', b),
  notifyBots: () => req<{ bots: Record<string, BotInfo>; log: { t: number; channel: string; user_name?: string; command: string; result: string }[] }>('GET', '/api/notify/bots'),
  notifyPair: (id: string) => req<{ code: string; seconds: number }>('POST', '/api/notify/pair', { id }),
  notifyUnpair: (id: string, user: string) => req<unknown>('POST', '/api/notify/unpair', { id, user }),
  notifyTest: (id: string) => req<{ sent: boolean }>('POST', '/api/notify/test', { id }),
  panelPause: (mode: 'stop' | 'pause' = 'stop') => req<{ paused: boolean }>('POST', '/api/panel/pause', { mode }),
  panelResume: () => req<{ paused: boolean }>('POST', '/api/panel/resume'),
  incidents: (limit = 100) => req<{ items: IncidentSummary[] }>('GET', `/api/incidents?limit=${limit}`),
  incident: (id: string) => req<Incident>('GET', `/api/incidents/${encodeURIComponent(id)}`),
  incidentFrameUrl: (id: string, name: string) => `/api/incidents/${encodeURIComponent(id)}/frame/${encodeURIComponent(name)}`,
  incidentToRecording: (id: string) => req<{ session: string; device: string; start: number; minutes: number }>('POST', `/api/incidents/${encodeURIComponent(id)}/recording`),
  incidentClipUrl: (id: string, name: string) => `/api/incidents/${encodeURIComponent(id)}/clip/${encodeURIComponent(name)}`,
  statesUrgentCheck: (ids: string[] = []) => req<UrgentCheck>('GET', `/api/states/urgent_check${ids.length ? `?ids=${ids.map(encodeURIComponent).join(',')}` : ''}`),
  statesJudge: (run = '') => req<JudgeInfo>('GET', `/api/states/judge${run ? `?run=${encodeURIComponent(run)}` : ''}`),
  statesRestore: (version: number, note = '') => req<Schema>('POST', '/api/states/restore', { version, note }),
  randomFrames: (n = 12, seed = 0) => req<string[]>('GET', `/api/frames/random?${qs({ n, seed })}`),
  framesBrowse: (session: string, device: string, offset = 0, limit = 24) =>
    req<{ total: number; offset: number; items: string[] }>('GET', `/api/frames/browse?${qs({ session, device, offset, limit })}`),
  rulesPreview: (state: StateDef, n = 24, seed = 0) => req<{ items: RulePreviewItem[]; templates: number; suggest?: RatioSuggestion }>('POST', '/api/rules/preview', { state, n, seed }),
  ruleGlyphs: (state: StateDef, frame: string) => req<GlyphsInfo>('POST', '/api/rules/glyphs', { state, frame }),
  ruleGlyphTeach: (state: StateDef, frame: string, index: number, char: string) =>
    req<GlyphsInfo>('POST', '/api/rules/glyph', { state, frame, index, char }),
  ruleTemplates: (stateId: string) => req<RuleTemplate[]>('GET', `/api/rules/templates/${stateId}`),
  ruleTemplateAdd: (b: { state_id: string; value: AnswerValue; frame: string; box: number[] }) => req<{ file: string }>('POST', '/api/rules/templates', b),
  ruleTemplateDelete: (stateId: string, file: string) => req<{ deleted: string }>('DELETE', `/api/rules/templates/${stateId}/${file}`),
  shadowStart: (b: { run: string; interval: number }) => req<JobInfo>('POST', '/api/shadow/start', b),
  shadowStop: () => req<{ stopping: boolean }>('POST', '/api/shadow/stop'),
  shadowStatus: () => req<{ status: ShadowStatus; job: JobInfo | null }>('GET', '/api/shadow/status'),
  shadowLog: (limit = 100) => req<ShadowLog[]>('GET', `/api/shadow/log?limit=${limit}`),
  shadowAct: (b: ShadowAct) => req<{ queued: boolean; busy?: { name?: string; sub?: string; now?: string; loop?: string | null; schedule: boolean } }>('POST', '/api/shadow/act', b),
  shadowActions: (device: string) => req<DeviceActions>('GET', `/api/shadow/actions/${encodeURIComponent(device)}`),
  shadowFlag: (device: string, note = '') => req<{ requested: boolean }>('POST', '/api/shadow/flag', { device, note }),
  shadowControlGet: () => req<Partial<ShadowControl>>('GET', '/api/shadow/control'),
  shadowControl: (b: Partial<Omit<ShadowControl, 'unblock'>> & { unblock?: boolean; resume?: { device: string; script: string; rule: string } }) => req<ShadowControl>('POST', '/api/shadow/control', b),
  shadowFlags: () => req<ShadowFlag[]>('GET', '/api/shadow/flags'),
  shadowStuck: () => req<{ t: number; device: string; frame: string; why: string; situations?: Record<string, string>; proc?: { sub_name?: string; now?: string } | null }[]>('GET', '/api/shadow/stuck'),
  scripts: () => req<ScriptsInfo>('GET', '/api/scripts'),
  scriptSave: (script: Script, note: string) => req<Script>('POST', '/api/scripts', { script, note }),
  scriptHistory: (id: string) => req<{ version: number; created: number; note: string }[]>('GET', `/api/scripts/${id}/history`),
  scriptVersion: (id: string, v: number) => req<Script>('GET', `/api/scripts/${id}/v/${v}`),
  scriptDelete: (id: string) => req<{ deleted: string }>('DELETE', `/api/scripts/${id}`),
  scriptTest: (script: Script) => req<ScriptTestResult>('POST', '/api/scripts/test', { script }),
  scriptsOrder: (order: string[]) => req<{ order: string[] }>('POST', '/api/scripts/order', { order }),
  variablesSave: (vars: VarDef[]) => req<{ vars: VarDef[] }>('POST', '/api/variables', { vars }),
  buttonSave: (button: LibButton, source: { snap?: string; frame?: string }) => req<LibButton>('POST', '/api/buttons', { button, ...source }),
  buttonDelete: (id: string) => req<{ deleted: string }>('DELETE', `/api/buttons/${id}`),
  listCapture: (list: string, device: string) => req<{ new: string[]; known: string[] }>('POST', '/api/lists/capture', { list, device }),
  runSub: (b: { device: string; sub: string; args: Record<string, ArgValue> }) => req<{ queued: boolean }>('POST', '/api/shadow/run_sub', b),
  buttonSnap: (device: string) => req<{ device: string; updated: number }>('POST', '/api/buttons/snap', { device }),
  scriptTemplate: (template: string) => req<{ kind: 'script' | 'sub' | 'guard_rules'; item: Script | SubScript | ScriptRule[] }>('POST', '/api/scripts/template', { template }),
  replayStart: (b: { session: string; device: string; start: number; minutes: number; script?: Script | null; sub_result: string }) =>
    req<{ id: string; job: string }>('POST', '/api/replay', b),
  shareExport: (subs: string[], with_calls: boolean) => req<ShareBundle>('POST', '/api/share/export', { subs, with_calls }),
  shareAnalyze: (bundle: unknown) => req<ShareAnalysis>('POST', '/api/share/analyze', { bundle }),
  shareImport: (bundle: unknown, plan: Record<string, Record<string, string>>) =>
    req<{ saved: string[]; created_buttons: string[]; added_variables: string[]; added_settings: string[] }>('POST', '/api/share/import', { bundle, plan }),
  outputs: () => req<OutputsInfo>('GET', '/api/outputs'),
  outputsSave: (outputs: OutputDef[]) => req<OutputsInfo>('PUT', '/api/outputs', { outputs }),
  outputTest: (id: string) => req<{ ok: boolean; status: number }>('POST', '/api/outputs/test', { id }),
  spec: () => req<{ format: number; kinds: Record<string, string> }>('GET', '/api/spec'),
  specCheck: (kind: 'script' | 'sub', doc: unknown) =>
    req<{ ok: boolean; errors: { path: string; message: string }[] }>('POST', '/api/spec/check', { kind, doc }),
  tests: () => req<TestsInfo>('GET', '/api/tests'),
  testsSave: (tests: TestCase[]) => req<TestsInfo>('PUT', '/api/tests', { tests }),
  testsRun: (ids: string[] = []) => req<JobInfo>('POST', '/api/tests/run', { ids }),
  testFromReplay: (replay: string, name: string) => req<TestsInfo & { id: string }>('POST', '/api/tests/from_replay', { replay, name }),
  replayResult: (id: string) => req<{ status: string; result?: ReplayResult; log?: string[] }>('GET', `/api/replay/${encodeURIComponent(id)}`),
  shadowTimeline: (device: string, minutes = 60) => req<TimelineRow[]>('GET', `/api/shadow/timeline?${qs({ device, minutes })}`),
  shadowVarSet: (b: { var: string; value: number; device?: string | null }) => req<{ queued: boolean }>('POST', '/api/shadow/vars', b),
  subSave: (sub: SubScript, note: string) => req<SubScript>('POST', '/api/subscripts', { sub, note }),
  subLayout: (layout: SubLayout) => req<SubLayout>('POST', '/api/subscripts/layout', layout),
  settings: () => req<SettingsInfo>('GET', '/api/settings'),
  settingsSave: (settings: SettingDecl[]) => req<{ settings: SettingDecl[] }>('POST', '/api/settings', { settings }),
  settingValue: (id: string, device: string | null, value: unknown) => req<{ old: unknown; new: unknown }>('POST', '/api/settings/value', { id, device, value }),
  settingChoices: (pickFrom: string, device?: string) =>
    req<{ choices: Choice[] }>('GET', `/api/settings/choices?pick_from=${encodeURIComponent(pickFrom)}${device ? `&device=${encodeURIComponent(device)}` : ''}`),
  subHistory: (id: string) => req<{ version: number; created: number; note: string }[]>('GET', `/api/subscripts/${id}/history`),
  subVersion: (id: string, v: number) => req<SubScript>('GET', `/api/subscripts/${id}/v/${v}`),
  subDelete: (id: string) => req<{ deleted: string }>('DELETE', `/api/subscripts/${id}`),
  trainPreview: (holdout: string[], neighbor: number) => req<DatasetSummary>('GET', `/api/train/preview?${qs({ holdout: holdout.join(','), neighbor })}`),
  trainStart: (c: TrainConfig) => req<JobInfo>('POST', '/api/train/start', c),
  trainStop: () => req<{ stopped: boolean }>('POST', '/api/train/stop'),
  trainRuns: () => req<{ runs: RunBrief[]; job: JobInfo | null }>('GET', '/api/train/runs'),
  trainRun: (id: string) => req<RunDetail>('GET', `/api/train/runs/${id}`),
  trainDelete: (id: string) => req<{ deleted: string }>('DELETE', `/api/train/runs/${id}`),
  galleries: () => req<{ galleries: { id: string; name: string }[]; cuts: Record<string, string> }>('GET', '/api/galleries'),
  gallery: (sid: string) => req<GalleryInfo>('GET', `/api/galleries/${sid}`),
  galleryName: (sid: string, b: { frame: string; ext: [number, number]; name: string }) => req<{ file: string }>('POST', `/api/galleries/${sid}/name`, b),
  galleryRename: (sid: string, file: string, name: string) => req<{ ok: boolean }>('POST', `/api/galleries/${sid}/rename`, { file, name }),
  galleryDelete: (sid: string, file: string) => req<{ ok: boolean }>('POST', `/api/galleries/${sid}/delete`, { file }),
}

export const galleryImageUrl = (sid: string, file: string) => `/api/galleries/${sid}/image/${encodeURIComponent(file)}`

/** Link that opens one frame in the Data browser, from a frame path like sessions/<s>/devices/<d>/frames/<id>.png */
export const browseLink = (frame: string) => {
  const m = frame.match(/sessions\/([^/]+)\/devices\/([^/]+)\/frames\/(\d+)\.png$/)
  return m ? `/browse?${qs({ session: m[1], device: m[2], open: m[3] })}` : null
}

export const shadowLiveUrl = (name: string, v: number) => `/api/shadow/live/${encodeURIComponent(name)}?v=${v}`
export const imageUrl = (path: string, thumb = 0) => `/api/image?${qs({ path, thumb: thumb || undefined })}`
/** full-size JPEG copy: much faster than the PNG, for pages that flip through many frames */
export const buttonImageUrl = (id: string, v?: number) => `/api/buttons/${id}/image?v=${v ?? 0}`
export const buttonSnapUrl = (device: string, v: number) => `/api/buttons/snap/${encodeURIComponent(device)}?v=${v}`
export const viewUrl = (path: string) => `/api/image?${qs({ path, view: 1 })}`
export const ruleTemplateUrl = (stateId: string, file: string) => `/api/rules/templates/${stateId}/${encodeURIComponent(file)}`

// ---------- the live workbench ----------
export interface WbSees {
  running: boolean; here?: boolean; updated?: number; hold_all?: Hold | null; state?: Record<string, ShadowState> | null
  hold?: Hold | null; proc?: { script_name?: string; sub_name?: string; now?: string } | null; manual?: { watched?: boolean; paused?: boolean } | null
}
export interface WbStateRead { value: AnswerValue | number | null; source: 'rule' | 'runner' | 'none' | string; conf?: number; ratio?: number | null; scores?: Record<string, number>; text?: string; gated?: string; error?: string; draft?: boolean }
export interface WbButton { id: string; label: string; x: number; y: number; find: boolean; box?: number[]; group?: string; found?: boolean; at?: [number, number] | null; score?: number | null }
export interface WbFrame { id: string; device: string; t: number; runner: WbSees; states: Record<string, WbStateRead>; buttons: WbButton[] }
export interface WbCondition { condition: string; now: 'holds' | 'does not hold' | 'unsure'; for_seconds?: number }
export interface WbRule { rule: string; name?: string; enabled: boolean; draft?: boolean; any_of: { all_of: WbCondition[]; group: string }[]; cooldown?: number; urgent: boolean }
export interface WbWhy {
  script: string; name?: string; mode: string; situation?: string; held?: Hold | null
  decision_now: { action?: string; text?: string; reason?: string; rule_name?: string }; rules_in_order: WbRule[]
}
export interface WbSpot {
  buttons: { id: string; label: string; dist: number; find: boolean; x: number; y: number }[]
  states: { state: string; name: string; roi: string; box: [number, number, number, number]; overlap: number }[]
  color?: HsvRange | null; ratio?: number; looks?: 'bar' | 'picture'
}
export interface WbRuleDraft { script: string; situation: string; first?: boolean; rule: ScriptRule }
export interface WbDraft {
  buttons: { button: LibButton; frame?: string }[]; states: StateDef[]
  refs: { state: string; value: AnswerValue; frame: string; box: number[]; glyph?: boolean }[]; answers: { state: string; value: AnswerValue | number; frame: string }[]
  subs: SubScript[]; rules: WbRuleDraft[]
}
export interface WbDraftView { doc: WbDraft; problems: string[]; impact: { what: string; users: string[] }[]; live?: Record<string, string[]> }
export interface WbStep {
  id: string; t: number; op: 'tap' | 'long_press' | 'swipe' | 'back' | 'text'; by: 'page' | 'hand'; x?: number; y?: number; x2?: number; y2?: number; ms?: number; text?: string
  frame?: string; states?: Record<string, unknown>; buttons?: WbSpot['buttons']; changes: { state: string; name: string; value: AnswerValue; value_name: string; own?: boolean }[]; gap: number | null
}
export interface WbTeach {
  active: boolean; device: string; started?: number; steps: WbStep[]; known: { sub: string; name: string; from: number; to: number }[]
  paused_here?: boolean; watching?: boolean; caps?: string[]; sees?: WbSees
}
export const wbDraftImageUrl = (name: string) => `/api/wb/draft/image/${encodeURIComponent(name)}`
export const wbLiveUrl = (device: string, v: number) => `/api/wb/live/${encodeURIComponent(device)}?v=${v}`
export const wbFrameUrl = (device: string, id: string) => `/api/wb/frames/${encodeURIComponent(device)}/${id}/image`
export interface WbGlyphs { count: number; text: string; value: number | null; taught: string[] }
export const wbApi = {
  sees: (device: string) => req<WbSees>('GET', `/api/wb/sees/${encodeURIComponent(device)}`),
  freeze: (device: string) => req<{ id: string; t: number }>('POST', '/api/wb/freeze', { device }),
  frames: (device: string) => req<{ items: { id: string; t: number }[] }>('GET', `/api/wb/frames/${encodeURIComponent(device)}`),
  frame: (device: string, id: string) => req<WbFrame>('GET', `/api/wb/frames/${encodeURIComponent(device)}/${id}`),
  at: (device: string, frame: string, box: number[]) => req<WbSpot>('POST', '/api/wb/at', { device, frame, box }),
  draft: () => req<WbDraftView>('GET', '/api/wb/draft'),
  draftSave: (doc: WbDraft) => req<{ problems: string[]; impact: WbDraftView['impact'] }>('POST', '/api/wb/draft', { doc }),
  keep: (device: string, frame: string) => req<{ frame: string }>('POST', '/api/wb/draft/keep', { device, frame }),
  newState: (b: { device: string; frame: string; box: number[]; name: string; kind: string }) => req<{ state: StateDef; doc: WbDraft }>('POST', '/api/wb/draft/state', b),
  draftLive: (device: string) => req<{ states: Record<string, WbStateRead> }>('GET', `/api/wb/draft/live/${encodeURIComponent(device)}`),
  glyphs: (device: string, frame: string, state: string) => req<WbGlyphs>('POST', '/api/wb/draft/glyphs', { device, frame, state }),
  glyphTeach: (device: string, frame: string, state: string, text: string) => req<WbGlyphs>('POST', '/api/wb/draft/glyphs/teach', { device, frame, state, text }),
  draftTry: () => req<{ items: { state: string; name: string; counts: Record<string, number>; unsure: number }[]; frames: number }>('POST', '/api/wb/draft/try'),
  why: (device: string, frame?: string | null) => req<{ items: WbWhy[]; running: boolean }>('POST', '/api/wb/draft/why', { device, frame: frame ?? undefined }),
  apply: (note: string, enable_rules: boolean) => req<{ id: string; counts: Record<string, number> }>('POST', '/api/wb/draft/apply', { note, enable_rules }),
  applied: () => req<{ items: { id: string; t: number; note: string; counts: Record<string, number>; undone?: number }[] }>('GET', '/api/wb/applied'),
  undo: (id: string) => req<{ failed: string[] }>('POST', `/api/wb/applied/${id}/undo`),
  teach: (device: string) => req<WbTeach>('GET', `/api/wb/teach/${encodeURIComponent(device)}`),
  teachStart: (device: string) => req<WbTeach>('POST', '/api/wb/teach/start', { device }),
  teachStop: (device: string) => req<WbTeach>('POST', '/api/wb/teach/stop', { device }),
  teachPress: (b: { device: string; op: string; x?: number; y?: number; x2?: number; y2?: number; ms?: number; text?: string }) => req<WbTeach>('POST', '/api/wb/teach/press', b),
  teachForget: (device: string, id: string) => req<WbTeach>('POST', '/api/wb/teach/forget', { device, id }),
}
