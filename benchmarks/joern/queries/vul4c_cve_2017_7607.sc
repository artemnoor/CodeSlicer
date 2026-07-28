@main def main(cpgFile: String, output: String) = {
  importCpg(cpgFile)
  import io.shiftleft.semanticcpg.language.locationCreator
  val source = cpg.call.nameExact("elf_getdata")
  val sink = cpg.method.nameExact("handle_gnu_hash").ast.isIdentifier.nameExact("chain")
  val flows = sink.reachableByFlows(source)
  flows.map(flow => flow.elements.map(node => Map[String, Any]("file" -> node.file.name.headOption.getOrElse(""), "lineNumber" -> node.lineNumber.getOrElse(0), "columnNumber" -> node.columnNumber.getOrElse(0), "nodeType" -> node.label))).toJson #> output
}
