package com.tinyburn.reproloop.lab

import java.security.MessageDigest

fun sha256(text: String): String = MessageDigest.getInstance("SHA-256")
    .digest(text.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it.toInt() and 255) }
fun quoted(value: String): String = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
fun validId(value: String, max: Int = 128): Boolean = value.length in 1..max && value.matches(Regex("[A-Za-z0-9_.:-]+"))
fun validTitle(value: String): Boolean = value.length in 1..64 && value == value.trim() && value.all { it.code in 32..126 }

data class Fixture(val id: String, val seed: Int, val variant: String,
                   val target: String = "Inbox", val other: String = "Archive") {
    init {
        require(validId(id, 64)); require(seed in 0..1_000_000)
        require(variant in listOf("A", "B", "C")); require(validTitle(target) && validTitle(other))
    }
    fun canonicalJson(): String = "{\"fixture_id\":" + quoted(id) +
        ",\"layout_variant\":" + quoted(variant) + ",\"non_target_id\":\"other\",\"non_target_title\":" +
        quoted(other) + ",\"seed\":" + seed + ",\"target_id\":\"target\",\"target_title\":" + quoted(target) + "}"
    val digest: String get() = sha256(canonicalJson())
}

data class LabEvent(val sequence: Long, val timestamp: Long, val action: String,
                    val taskId: String, val before: String, val draft: String, val after: String,
                    val target: String, val other: String, val cancelCount: Int)

class LabModel(val fixture: Fixture, val runId: String, val generation: Long,
               val faulty: Boolean, private val clock: () -> Long = System::currentTimeMillis) {
    init { require(validId(runId)); require(generation in 1..Int.MAX_VALUE.toLong()) }
    var targetTitle = fixture.target; private set
    var otherTitle = fixture.other; private set
    var sequence = 0L; private set
    var cancelCount = 0; private set
    val cancelOrder = mutableListOf<Long>()
    var createdAt = clock(); private set
    var updatedAt = createdAt; private set
    var selectedId: String? = null; private set
    var editingId: String? = null; private set
    var draftTitle: String? = null; private set
    fun title(id: String): String = when (id) { "target" -> targetTitle; "other" -> otherTitle; else -> error("Unknown task") }
    private fun put(id: String, value: String) { if (id == "target") targetTitle = value else { require(id == "other"); otherTitle = value } }
    private fun event(action: String, id: String = "", before: String = "", draft: String = "", after: String = ""): LabEvent {
        sequence += 1; updatedAt = maxOf(updatedAt, clock())
        return LabEvent(sequence, updatedAt, action, id, before, draft, after, targetTitle, otherTitle, cancelCount)
    }
    fun loaded(): LabEvent { check(sequence == 0L); return event("fixture_loaded") }
    fun select(id: String): LabEvent { check(editingId == null); title(id); selectedId = id; return event("task_open", id, title(id), "", title(id)) }
    fun openRename(): LabEvent {
        check(editingId == null); val id = checkNotNull(selectedId)
        editingId = id; draftTitle = title(id); return event("rename_open", id, title(id), title(id), title(id))
    }
    fun presetToday(): LabEvent {
        val id = checkNotNull(editingId); draftTitle = "Today"
        return event("select_preset", id, title(id), "Today", title(id))
    }
    fun cancel(): LabEvent {
        val id = checkNotNull(editingId); val before = title(id); val draft = checkNotNull(draftTitle)
        // The ONLY behavioral fault switch: Cancel incorrectly saves the draft.
        if (faulty) put(id, draft)
        editingId = null; draftTitle = null; cancelCount += 1
        val e = event("cancel_edit", id, before, draft, title(id)); cancelOrder.add(e.sequence); return e
    }
    fun save(): LabEvent {
        val id = checkNotNull(editingId); val before = title(id); val draft = checkNotNull(draftTitle)
        put(id, draft); editingId = null; draftTitle = null
        return event("save_edit", id, before, draft, title(id))
    }
    fun dismiss(): LabEvent {
        val id = checkNotNull(editingId); val before = title(id); val draft = checkNotNull(draftTitle)
        editingId = null; draftTitle = null; return event("dismiss_edit", id, before, draft, before)
    }
    fun restore(target: String, other: String, seq: Long, count: Int, order: List<Long>, updated: Long, created: Long) {
        require(validTitle(target) && validTitle(other)); require(seq >= 1 && count >= 0)
        require(order.size == count && order.all { it in 1..seq } && order.zipWithNext().all { it.first < it.second })
        require(created >= 0 && updated >= created)
        createdAt = created
        targetTitle = target; otherTitle = other; sequence = seq; cancelCount = count
        cancelOrder.clear(); cancelOrder.addAll(order); updatedAt = updated
    }
}
