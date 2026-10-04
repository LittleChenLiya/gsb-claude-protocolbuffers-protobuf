// Protocol Buffers - Google's data interchange format
// Copyright 2008 Google Inc.  All rights reserved.
// https://developers.google.com/protocol-buffers/
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are
// met:
//
//     * Redistributions of source code must retain the above copyright
// notice, this list of conditions and the following disclaimer.
//     * Redistributions in binary form must reproduce the above
// copyright notice, this list of conditions and the following disclaimer
// in the documentation and/or other materials provided with the
// distribution.
//     * Neither the name of Google Inc. nor the names of its
// contributors may be used to endorse or promote products derived from
// this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
// "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
// LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
// A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
// OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
// SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
// LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
// DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
// THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
// (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
// OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

#ifndef GOOGLE_PROTOBUF_COMPILER_IMPORT_DIAGNOSTIC_H__
#define GOOGLE_PROTOBUF_COMPILER_IMPORT_DIAGNOSTIC_H__

#include <string>
#include <vector>

#include "google/protobuf/descriptor.h"

// Read-only import diagnostics for the protocol compiler.
//
// After a FileDescriptor has been built successfully, this analyzes, for
// every type, extension, service method and custom option referenced by
// the file, which import chain makes it visible, and classifies each
// import of the file as directly used, used only through a public
// re-export, weak, a pure re-export, or unused.  The analysis is purely
// observational: it never mutates the DescriptorPool and it relies only on
// Descriptor objects, so it also works for files that were loaded without
// SourceCodeInfo (e.g. from a --descriptor_set_in file).
namespace google {
namespace protobuf {
namespace compiler {

// How a single import of the audited file is used.
enum class ImportUsageKind {
  // Symbols defined in the imported file itself are referenced.
  kUsedDirect = 0,
  // No symbol of the imported file itself is referenced, but symbols from
  // files it publicly re-exports are.
  kUsedPublicTransitive = 1,
  // Nothing from the import or its public re-exports is referenced.
  kUnused = 2,
  // Weak import.  Weak imports are never reported as unused.
  kWeak = 3,
  // The import is not referenced by this file, but it is re-exported with
  // "import public", so removing it may break importers of this file.
  kPublicReexport = 4,
};

// Visibility information for one referenced symbol: which file defines it
// and through which import chain it is visible to the audited file.
struct ImportVisibilityWitness {
  std::string symbol;         // Fully-qualified symbol name.
  std::string defining_file;  // File that defines the symbol.
  // The witness chain of file names, starting at the audited file and
  // ending at defining_file.  When several equivalent chains exist, the
  // witness is chosen deterministically as the lexicographically smallest
  // chain (by file name) among the shortest ones.
  std::vector<std::string> chain;
  // True when at least one edge of the witness chain is a public import.
  bool via_public_import = false;
  // All other equivalent chains (sorted), kept so that ambiguity is
  // visible to the caller.  Empty when the witness is unique.
  std::vector<std::vector<std::string>> equivalent_chains;
};

// Diagnostic for one import of the audited file.
struct ImportDiagnosticEntry {
  std::string import;  // Imported file name, as written in the import.
  ImportUsageKind usage = ImportUsageKind::kUnused;
  // True when this import alone can be removed without changing how the
  // file compiles: either it is entirely unused, or every symbol it makes
  // visible is also visible through another import chain.
  bool removable = false;
  bool is_weak = false;
  bool is_public = false;
  // Symbols attributed to this import ("<full name> (<kind>)"), sorted.
  std::vector<std::string> used_symbols;
  // Human-readable justification for the classification.
  std::string reason;
};

struct ImportDiagnosticReport {
  std::string file;  // Name of the audited file.
  // One entry per import of the file, in declaration order.
  std::vector<ImportDiagnosticEntry> imports;
  // One witness per referenced external symbol, sorted by symbol name.
  std::vector<ImportVisibilityWitness> witnesses;
};

// Analyzes the imports of `file`, which must have been built successfully
// by a DescriptorPool.  This is a read-only operation.
ImportDiagnosticReport AnalyzeImportVisibility(const FileDescriptor& file);

// Renders the report as deterministic, human-readable text.
std::string FormatImportDiagnosticReport(const ImportDiagnosticReport& report);

}  // namespace compiler
}  // namespace protobuf
}  // namespace google

#endif  // GOOGLE_PROTOBUF_COMPILER_IMPORT_DIAGNOSTIC_H__
