@main def main(cpgFile: String, output: String) = {
  importCpg(cpgFile)
  import io.shiftleft.semanticcpg.language.locationCreator
  val source = cpg.method.nameExact("readObject").parameter
  val sink = cpg.method.nameExact("readObject").ast.isCall.nameExact("defaultReadObject")
  val flows = sink.reachableByFlows(source)
  flows.map(flow => flow.elements.map(node => Map[String, Any]("file" -> node.file.name.headOption.getOrElse(""), "lineNumber" -> node.lineNumber.getOrElse(0), "columnNumber" -> node.columnNumber.getOrElse(0), "nodeType" -> node.label, "code" -> node.code))).toJson #> output
}
