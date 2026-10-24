package com.sphereplatform.agent.service

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import java.io.File
import javax.xml.parsers.DocumentBuilderFactory

class SphereAgentForegroundServicePolicyTest {
    @Test fun `persistent agent declares the special-use service contract and permission`() {
        val document = manifestDocument()
        val androidNs = "http://schemas.android.com/apk/res/android"
        val services = document.getElementsByTagName("service")
        val service = (0 until services.length).map { services.item(it) as org.w3c.dom.Element }
            .single { it.getAttributeNS(androidNs, "name") == ".service.SphereAgentService" }

        assertEquals("specialUse", service.getAttributeNS(androidNs, "foregroundServiceType"))
        val permissions = document.getElementsByTagName("uses-permission")
        assertEquals(
            1,
            (0 until permissions.length).count {
                (permissions.item(it) as org.w3c.dom.Element)
                    .getAttributeNS(androidNs, "name") == "android.permission.FOREGROUND_SERVICE_SPECIAL_USE"
            },
        )
        val properties = service.getElementsByTagName("property")
        val subtype = (0 until properties.length).map { properties.item(it) as org.w3c.dom.Element }
            .single { it.getAttributeNS(androidNs, "name") == "android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE" }
        assertEquals(
            "persistent_device_management_control_channel",
            subtype.getAttributeNS(androidNs, "value"),
        )
    }

    @Test fun `ordinary APK does not claim protected platform permissions or system persistence`() {
        val document = manifestDocument()
        val androidNs = "http://schemas.android.com/apk/res/android"
        val permissions = document.getElementsByTagName("uses-permission")
            .let { nodes -> (0 until nodes.length).map { nodes.item(it) as org.w3c.dom.Element } }
            .map { it.getAttributeNS(androidNs, "name") }

        assertFalse("INSTALL_PACKAGES is system-only", "android.permission.INSTALL_PACKAGES" in permissions)
        assertFalse("READ_LOGS is system-only", "android.permission.READ_LOGS" in permissions)

        val application = document.getElementsByTagName("application").item(0) as org.w3c.dom.Element
        assertFalse(
            "android:persistent is only meaningful for system applications",
            application.getAttributeNS(androidNs, "persistent").equals("true", ignoreCase = true),
        )
    }

    private fun manifestDocument(): org.w3c.dom.Document {
        val manifestFile = sequenceOf(
            File("src/main/AndroidManifest.xml"),
            File("app/src/main/AndroidManifest.xml"),
            File("android/app/src/main/AndroidManifest.xml"),
        ).firstOrNull(File::isFile) ?: error("AndroidManifest.xml not found from ${System.getProperty("user.dir")}")
        val factory = DocumentBuilderFactory.newInstance().apply {
            isNamespaceAware = true
            setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
            setFeature("http://xml.org/sax/features/external-general-entities", false)
            setFeature("http://xml.org/sax/features/external-parameter-entities", false)
        }
        return factory.newDocumentBuilder().parse(manifestFile)
    }
}
