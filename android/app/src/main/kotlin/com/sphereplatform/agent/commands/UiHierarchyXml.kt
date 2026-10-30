package com.sphereplatform.agent.commands

import org.w3c.dom.Document
import org.w3c.dom.Node
import org.xml.sax.InputSource
import org.xml.sax.Attributes
import org.xml.sax.SAXException
import org.xml.sax.SAXParseException
import org.xml.sax.helpers.DefaultHandler
import java.io.StringReader
import javax.xml.parsers.DocumentBuilderFactory
import javax.xml.parsers.SAXParserFactory

/** Accept only a complete bounded hierarchy; never expand a DTD or external entity. */
internal object UiHierarchyXml {
    data class Snapshot(val xml: String, val document: Document)
    const val MAX_BYTES = 512 * 1024
    private const val MAX_DEPTH = 64
    private const val MAX_NODES = 10_000
    private val declaration = Regex("<!\\s*(DOCTYPE|ENTITY)\\b", RegexOption.IGNORE_CASE)

    fun parse(xml: String): Document {
        require(xml.toByteArray(Charsets.UTF_8).size <= MAX_BYTES) { "ui_xml_byte_limit" }
        require(!declaration.containsMatchIn(xml)) { "ui_xml_dtd_forbidden" }
        // Enforce depth before constructing a DOM or walking recursively.
        val reader = SAXParserFactory.newInstance().newSAXParser().xmlReader
        reader.entityResolver = org.xml.sax.EntityResolver { _, _ ->
            throw SAXException("ui_xml_external_entity_forbidden")
        }
        val budget = object : DefaultHandler() {
            private var depth = 0
            private var nodes = 0
            override fun startElement(uri: String?, localName: String?, qName: String?, attributes: Attributes?) {
                depth++
                nodes++
                require(depth <= MAX_DEPTH) { "ui_xml_depth_limit" }
                require(nodes <= MAX_NODES) { "ui_xml_node_limit" }
            }
            override fun endElement(uri: String?, localName: String?, qName: String?) { depth-- }
            override fun error(e: SAXParseException) { throw SAXException("ui_xml_invalid") }
            override fun fatalError(e: SAXParseException) { throw SAXException("ui_xml_invalid") }
        }
        reader.contentHandler = budget
        reader.errorHandler = budget
        reader.parse(InputSource(StringReader(xml)))
        val factory = DocumentBuilderFactory.newInstance().apply {
            isNamespaceAware = false
            isExpandEntityReferences = false
            // Android XML implementations differ in supported optional SAX features.
            // The explicit DTD guard and rejecting resolver remain mandatory.
            runCatching { setFeature("http://apache.org/xml/features/disallow-doctype-decl", true) }
            runCatching { setFeature("http://xml.org/sax/features/external-general-entities", false) }
            runCatching { setFeature("http://xml.org/sax/features/external-parameter-entities", false) }
            runCatching { setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false) }
        }
        val builder = factory.newDocumentBuilder().apply {
            setEntityResolver { _, _ -> throw SAXException("ui_xml_external_entity_forbidden") }
            setErrorHandler(object : DefaultHandler() {
                override fun error(e: SAXParseException) { throw SAXException("ui_xml_invalid") }
                override fun fatalError(e: SAXParseException) { throw SAXException("ui_xml_invalid") }
            })
        }
        val document = builder.parse(InputSource(StringReader(xml)))
        require(document.documentElement?.tagName == "hierarchy") { "ui_xml_root_invalid" }
        var count = 0
        fun visit(node: Node, depth: Int) {
            require(depth <= MAX_DEPTH) { "ui_xml_depth_limit" }
            count++
            require(count <= MAX_NODES) { "ui_xml_node_limit" }
            var child = node.firstChild
            while (child != null) {
                visit(child, depth + 1)
                child = child.nextSibling
            }
        }
        visit(document.documentElement, 1)
        return document
    }
}
