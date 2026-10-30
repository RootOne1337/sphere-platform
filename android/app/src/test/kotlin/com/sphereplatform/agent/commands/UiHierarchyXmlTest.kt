package com.sphereplatform.agent.commands

import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)

class UiHierarchyXmlTest {
    @Test fun `complete hierarchy retains all safe attributes and UTF8 text`() {
        val doc = UiHierarchyXml.parse("""<hierarchy rotation="1"><node text="Привет &amp; мир" bounds="[1,2][3,4]" custom="value" /></hierarchy>""")
        val node = doc.getElementsByTagName("node").item(0) as org.w3c.dom.Element
        assertEquals("Привет & мир", node.getAttribute("text"))
        assertEquals("value", node.getAttribute("custom"))
    }

    @Test fun `incomplete hierarchy with a valid first node is rejected`() {
        assertThrows(Exception::class.java) {
            UiHierarchyXml.parse("""<hierarchy><node text="target" bounds="[1,2][3,4]" />""")
        }
    }

    @Test fun `DTD external and internal entities are rejected before expansion`() {
        for (xml in listOf(
            """<!DOCTYPE hierarchy SYSTEM "file:///private/secret"><hierarchy/>""",
            """<!DOCTYPE hierarchy [<!ENTITY test "secret">]><hierarchy><node text="&test;"/></hierarchy>""",
        )) {
            val error = assertThrows(IllegalArgumentException::class.java) { UiHierarchyXml.parse(xml) }
            assertEquals("ui_xml_dtd_forbidden", error.message)
        }
    }

    @Test fun `UTF8 byte budget rejects fewer than maximum chars`() {
        val xml = "<hierarchy text='" + "界".repeat(UiHierarchyXml.MAX_BYTES / 2) + "'/>"
        assertTrue(xml.length < UiHierarchyXml.MAX_BYTES)
        assertEquals("ui_xml_byte_limit", assertThrows(IllegalArgumentException::class.java) {
            UiHierarchyXml.parse(xml)
        }.message)
    }

    @Test fun `depth and node counts are bounded`() {
        val nested = "<hierarchy>" + "<node>".repeat(65) + "</node>".repeat(65) + "</hierarchy>"
        assertEquals("ui_xml_depth_limit", assertThrows(IllegalArgumentException::class.java) {
            UiHierarchyXml.parse(nested)
        }.message)
        val excessivelyDeep = "<hierarchy>" + "<node>".repeat(15_000) + "</node>".repeat(15_000) + "</hierarchy>"
        assertEquals("ui_xml_depth_limit", assertThrows(IllegalArgumentException::class.java) {
            UiHierarchyXml.parse(excessivelyDeep)
        }.message)
        val wide = "<hierarchy>" + "<node/>".repeat(10_000) + "</hierarchy>"
        assertEquals("ui_xml_node_limit", assertThrows(IllegalArgumentException::class.java) {
            UiHierarchyXml.parse(wide)
        }.message)
    }

    @Test fun `non hierarchy root cannot be used for input mapping`() {
        assertEquals("ui_xml_root_invalid", assertThrows(IllegalArgumentException::class.java) {
            UiHierarchyXml.parse("<other><hierarchy/></other>")
        }.message)
    }
}
