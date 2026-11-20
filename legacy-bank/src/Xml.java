import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.OutputKeys;
import javax.xml.transform.Transformer;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import java.io.ByteArrayInputStream;
import java.io.StringWriter;
import java.math.BigDecimal;
import java.util.List;

/** XML (DOM) reading and writing with javax.xml only. */
public class Xml {

    /** DOM parser hardened against XXE / entity expansion attacks. */
    static DocumentBuilder secureBuilder() throws Exception {
        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);  // no DTD at all
        f.setFeature("http://xml.org/sax/features/external-general-entities", false);
        f.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
        f.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
        f.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
        f.setXIncludeAware(false);
        f.setExpandEntityReferences(false);
        f.setNamespaceAware(false);
        return f.newDocumentBuilder();
    }

    static SettlementOrder parseOrder(byte[] xml) throws Exception {
        DocumentBuilder builder = secureBuilder();
        builder.setErrorHandler(null);  // no stderr noise; errors become exceptions
        Document doc = builder.parse(new ByteArrayInputStream(xml));
        Element root = doc.getDocumentElement();
        if (!"SettlementOrder".equals(root.getTagName()) || !"1.0".equals(root.getAttribute("version"))) {
            throw new IllegalArgumentException("esperado <SettlementOrder version=\"1.0\">");
        }
        Element amount = child(root, "Amount");
        Element converted = child(root, "ConvertedAmount");
        Element signature = child(root, "Signature");
        if (!"Ed25519".equals(signature.getAttribute("alg"))) {
            throw new IllegalArgumentException("algoritmo de assinatura não suportado");
        }
        return new SettlementOrder(
                text(root, "TxId"), text(root, "FromIban"), text(root, "ToIban"),
                new BigDecimal(amount.getTextContent().trim()), amount.getAttribute("currency"),
                new BigDecimal(converted.getTextContent().trim()), converted.getAttribute("currency"),
                text(root, "Timestamp"), text(root, "Sha256"), signature.getTextContent().trim());
    }

    static Element child(Element parent, String tag) {
        NodeList list = parent.getElementsByTagName(tag);
        if (list.getLength() != 1) {
            throw new IllegalArgumentException("elemento <" + tag + "> em falta ou repetido");
        }
        return (Element) list.item(0);
    }

    static String text(Element parent, String tag) {
        return child(parent, tag).getTextContent().trim();
    }

    static String ackToXml(LegacyBank.Ack ack, SettlementCrypto crypto) {
        try {
            Document doc = DocumentBuilderFactory.newInstance().newDocumentBuilder().newDocument();
            Element root = doc.createElement("SettlementAck");
            root.setAttribute("version", "1.0");
            doc.appendChild(root);
            add(doc, root, "TxId", ack.txId());
            add(doc, root, "Status", ack.status());
            add(doc, root, "Reason", ack.reason());
            add(doc, root, "Timestamp", ack.timestamp());
            add(doc, root, "Sha256", SettlementCrypto.sha256Hex(ack.canonical()));
            add(doc, root, "Signature", crypto.sign(ack.canonical())).setAttribute("alg", "Ed25519");
            return serialize(doc);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    static String settlementsToXml(List<Ledger.Record> records) {
        try {
            Document doc = DocumentBuilderFactory.newInstance().newDocumentBuilder().newDocument();
            Element root = doc.createElement("Settlements");
            root.setAttribute("count", String.valueOf(records.size()));
            doc.appendChild(root);
            for (Ledger.Record r : records) {
                Element s = add(doc, root, "Settlement", null);
                add(doc, s, "TxId", r.txId());
                add(doc, s, "FromIban", r.fromIban());
                add(doc, s, "ToIban", r.toIban());
                add(doc, s, "Amount", r.amount().toPlainString()).setAttribute("currency", r.currency());
                add(doc, s, "ConvertedAmount", r.convertedAmount().toPlainString())
                        .setAttribute("currency", r.convertedCurrency());
                add(doc, s, "Timestamp", r.timestamp());
            }
            return serialize(doc);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    static Element add(Document doc, Element parent, String tag, String text) {
        Element e = doc.createElement(tag);
        if (text != null) {
            e.setTextContent(text);
        }
        parent.appendChild(e);
        return e;
    }

    static String serialize(Document doc) throws Exception {
        Transformer t = TransformerFactory.newInstance().newTransformer();
        t.setOutputProperty(OutputKeys.INDENT, "yes");
        t.setOutputProperty(OutputKeys.ENCODING, "UTF-8");
        t.setOutputProperty("{http://xml.apache.org/xslt}indent-amount", "2");
        StringWriter out = new StringWriter();
        t.transform(new DOMSource(doc), new StreamResult(out));
        return out.toString();
    }
}
