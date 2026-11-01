package com.tinyburn.reproloop.lab

import android.app.Activity
import android.app.Dialog
import android.content.Intent
import android.os.Bundle
import android.util.AtomicFile
import android.view.View
import android.view.Window
import android.view.WindowManager
import android.graphics.Color
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream

class MainActivity : Activity() {
    private lateinit var model: LabModel
    private val stateFile get() = File(filesDir, "state.json")
    private val eventsFile get() = File(filesDir, "events.jsonl")
    private var detail = false
    private var failed = false
    private var activeDialog: Dialog? = null
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState); immersive(window); load(intent) }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) immersive(window)
    }
    @Suppress("DEPRECATION")
    private fun immersive(ownedWindow: Window?) {
        if (ownedWindow == null) return
        ownedWindow.setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN, WindowManager.LayoutParams.FLAG_FULLSCREEN)
        ownedWindow.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
            View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
        ownedWindow.attributes = ownedWindow.attributes.apply { windowAnimations = 0 }
    }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); load(intent) }

    private fun load(intent: Intent) {
        try {
            activeDialog?.setOnCancelListener(null); activeDialog?.dismiss(); activeDialog = null
            failed = false; detail = false
            val reset = intent.extras?.get("reset_fixture")
            require(reset == null || reset is Boolean) { "reset_fixture must be boolean" }
            if (reset == true) {
                check(BuildConfig.DEBUG)
                val allowed = setOf("reset_fixture", "fixture_id", "run_id", "generation", "seed", "layout_variant", "target_title", "non_target_title", "expected_fixture_sha256")
                require(intent.extras!!.keySet().all { it in allowed }) { "Unknown fixture extra" }
                fun str(key: String, default: String? = null): String {
                    val raw = intent.extras?.get(key)
                    if (raw == null) return requireNotNull(default) { "Missing $key" }
                    require(raw is String) { "Wrong type $key" }; return raw
                }
                val seed = intent.extras?.get("seed") ?: 0
                val generation = intent.extras?.get("generation") ?: 1L
                require(seed is Int && generation is Long) { "seed=int, generation=long required" }
                val f = Fixture(str("fixture_id"), seed, str("layout_variant", "A"), str("target_title", "Inbox"), str("non_target_title", "Archive"))
                val expected = str("expected_fixture_sha256", "")
                require(expected.isEmpty() || expected.matches(Regex("[0-9a-f]{64}")) && expected == f.digest) { "Fixture digest mismatch" }
                model = LabModel(f, str("run_id"), generation, BuildConfig.FAULTY)
                persist(model.loaded(), true)
            } else if (stateFile.exists()) {
                require(stateFile.length() <= 1_000_000)
                val obj = JSONObject(stateFile.readText())
                require(obj.getString("build_mode") == BuildConfig.MODE) { "Build changed: explicit reset required" }
                val f = obj.getJSONObject("fixture")
                val fixture = Fixture(f.getString("fixture_id"), f.getInt("seed"), f.getString("layout_variant"), f.getString("target_title"), f.getString("non_target_title"))
                require(fixture.digest == obj.getString("fixture_sha256"))
                model = LabModel(fixture, obj.getString("run_id"), obj.getLong("generation"), BuildConfig.FAULTY)
                val order = obj.getJSONArray("cancel_order")
                model.restore(obj.getString("target_title"), obj.getString("non_target_title"), obj.getLong("sequence"), obj.getInt("cancel_count"),
                    (0 until order.length()).map { order.getLong(it) }, obj.getLong("updated_at_unix_ms"), obj.getLong("created_at_unix_ms"))
                require(eventsFile.exists() && eventsFile.length() <= 2_000_000)
                val last = JSONObject(eventsFile.readLines().last())
                require(last.getLong("sequence") == model.sequence && last.getString("run_id") == model.runId && last.getString("fixture_sha256") == fixture.digest && last.getString("build_mode") == BuildConfig.MODE) { "State/event mismatch" }
            } else {
                model = LabModel(Fixture("DEV-default", 0, "A"), "default-run", 1, BuildConfig.FAULTY)
                persist(model.loaded(), true)
            }
            render()
        } catch (e: Exception) { errorView(e) }
    }

    private fun metadata(): JSONObject = JSONObject().put("schema_version", 1).put("package", packageName)
        .put("build_mode", BuildConfig.MODE).put("fixture_id", model.fixture.id).put("fixture_sha256", model.fixture.digest)
        .put("seed", model.fixture.seed).put("layout_variant", model.fixture.variant).put("run_id", model.runId).put("generation", model.generation)
    private fun persist(e: LabEvent, reset: Boolean = false) {
        val event = metadata().put("sequence", e.sequence).put("timestamp_unix_ms", e.timestamp).put("action", e.action)
            .put("task_id", e.taskId).put("before_title", e.before).put("draft_title", e.draft).put("after_title", e.after)
            .put("cancel_count", e.cancelCount).put("target_title", e.target).put("non_target_title", e.other)
        FileOutputStream(eventsFile, !reset).use { out -> out.write((event.toString() + "\n").toByteArray(Charsets.UTF_8)); out.fd.sync() }
        val state = metadata().put("fixture", JSONObject(model.fixture.canonicalJson()))
            .put("target_id", "target").put("target_title", model.targetTitle).put("non_target_id", "other").put("non_target_title", model.otherTitle)
            .put("sequence", model.sequence).put("cancel_count", model.cancelCount).put("cancel_order", JSONArray(model.cancelOrder))
            .put("created_at_unix_ms", model.createdAt).put("updated_at_unix_ms", model.updatedAt).put("last_action", e.action)
        val atomic = AtomicFile(stateFile)
        val out = atomic.startWrite()
        try { out.write(state.toString().toByteArray(Charsets.UTF_8)); atomic.finishWrite(out) }
        catch (t: Throwable) { atomic.failWrite(out); throw t }
    }
    private fun act(block: () -> LabEvent) {
        if (failed) return
        try { persist(block()) } catch (e: Exception) { errorView(e) }
    }
    private fun errorView(e: Exception) {
        failed = true
        setContentView(TextView(this).apply { text = "Fixture/evidence unavailable. Trusted reset required.\n" + e.javaClass.simpleName; textSize = 20f; setPadding(24, 32, 24, 24) })
    }
    private fun column(): LinearLayout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(24, 24, 24, 24) }
    private fun label(text: String, viewId: Int = View.NO_ID): TextView = TextView(this).apply { this.text = text; textSize = 22f; id = viewId; setPadding(8, 12, 8, 12) }
    private fun button(text: String, viewId: Int, click: () -> Unit): Button = Button(this).apply {
        this.text = text; contentDescription = text; id = viewId; isAllCaps = false; minHeight = 56
        // Static app-local paint: no ripple/elevation animation or click audio.
        setBackgroundColor(Color.rgb(225, 235, 245)); backgroundTintList = null
        foreground = null; stateListAnimator = null; isSoundEffectsEnabled = false; isHapticFeedbackEnabled = false
        setOnClickListener { if (!failed) click() }
    }
    private fun render() {
        if (failed) return
        val root = column()
        root.addView(label("PocketTasks Lab", R.id.screen_title))
        if (!detail || model.fixture.variant != "C") {
            root.addView(label("Select a task"))
            val target = button("Target task: " + model.targetTitle, R.id.task_target) { act { model.select("target") }; detail = model.fixture.variant == "C"; render() }
            val other = button("Other task: " + model.otherTitle, R.id.task_other) { act { model.select("other") }; detail = model.fixture.variant == "C"; render() }
            if (model.fixture.variant == "B") { root.addView(other); root.addView(target) }
            else { root.addView(target); root.addView(other) }
        }
        if (model.selectedId != null) {
            val selected = label("Selected: " + model.title(model.selectedId!!), R.id.selected_title)
            val rename = button("Rename", R.id.rename_open) { showEditor() }
            if (model.fixture.variant == "B") { root.addView(rename); root.addView(selected) }
            else { root.addView(selected); root.addView(rename) }
            if (detail && model.fixture.variant == "C") root.addView(button("Back to tasks", R.id.back_to_tasks) { detail = false; render() })
        }
        setContentView(root)
    }
    private fun showEditor() {
        act { model.openRename() }; if (failed) return
        val dialog = Dialog(this)
        activeDialog = dialog
        val root = column(); root.addView(label("Rename task"))
        val preview = label("Draft: " + model.draftTitle)
        root.addView(preview)
        root.addView(button("Today", R.id.preset_today) { act { model.presetToday() }; preview.text = "Draft: " + model.draftTitle })
        val cancel = button("Cancel", R.id.cancel_edit) { act { model.cancel() }; dialog.dismiss(); render() }
        val save = button("Save", R.id.save_edit) { act { model.save() }; dialog.dismiss(); render() }
        if (model.fixture.variant == "B") { root.addView(save); root.addView(cancel) }
        else { root.addView(cancel); root.addView(save) }
        dialog.setContentView(root)
        dialog.setOnCancelListener { if (model.editingId != null) { act { model.dismiss() }; render() } }
        dialog.show()
        immersive(dialog.window)
    }
}
