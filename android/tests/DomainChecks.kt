package com.tinyburn.reproloop.lab

fun main() {
    var checks = 0
    fun verify(value: Boolean) { check(value); checks++ }
    for (variant in listOf("A", "B", "C")) for (faulty in listOf(false, true)) {
        var now = 1000L
        val f = Fixture("DEV01", 0, variant)
        val m = LabModel(f, "run-1", 1, faulty) { now++ }
        verify(m.loaded().sequence == 1L)
        m.select("target"); m.openRename(); m.presetToday()
        val e = m.cancel()
        verify(e.action == "cancel_edit" && e.sequence == 5L)
        verify(m.cancelCount == 1 && m.cancelOrder == listOf(5L))
        verify(m.targetTitle == if (faulty) "Today" else "Inbox")
        verify(m.otherTitle == "Archive")
        verify(e.after == m.targetTitle && e.draft == "Today")
        verify(m.updatedAt >= m.createdAt)
        val m2 = LabModel(f, "run-2", 1, faulty)
        m2.loaded(); m2.select("target"); m2.openRename(); m2.presetToday(); m2.dismiss()
        verify(m2.targetTitle == "Inbox" && m2.cancelCount == 0)
        val m3 = LabModel(f, "run-3", 1, faulty)
        m3.loaded(); m3.select("other"); m3.openRename(); m3.presetToday(); m3.cancel()
        verify(m3.targetTitle == "Inbox")
        verify(m3.otherTitle == if (faulty) "Today" else "Archive")
    }
    verify(Fixture("DEV01", 0, "A").canonicalJson() == "{\"fixture_id\":\"DEV01\",\"layout_variant\":\"A\",\"non_target_id\":\"other\",\"non_target_title\":\"Archive\",\"seed\":0,\"target_id\":\"target\",\"target_title\":\"Inbox\"}")
    verify(Fixture("DEV01", 0, "A").digest == "78156d189085309b8cbcd982f0b624245ce3131717d9d1639cb4bad0da8cda97")
    verify(Fixture("DEV01", 0, "A").digest.length == 64)
    for (bad in listOf("", " ", "../escape", "x".repeat(129))) {
        verify(!validId(bad))
    }
    verify(!validTitle(" hidden "))
    println("PASS domain checks=$checks; modes=2 variants=3; no Android/UI/persistence/device executed")
}
