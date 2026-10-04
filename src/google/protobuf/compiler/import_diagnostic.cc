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

#include "google/protobuf/compiler/import_diagnostic.h"

#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "absl/strings/str_cat.h"
#include "absl/strings/str_join.h"
#include "google/protobuf/descriptor.h"
#include "google/protobuf/descriptor.pb.h"
#include "google/protobuf/dynamic_message.h"
#include "google/protobuf/message.h"

namespace google {
namespace protobuf {
namespace compiler {
namespace {

// A single reference from the audited file to a symbol defined in another
// file.
struct SymbolReference {
  std::string name;       // Fully-qualified name of the referenced symbol.
  std::string kind;       // "message", "enum", "custom option", ...
  const FileDescriptor* defined_in = nullptr;
};

// Collects every symbol reference of a file, recording the file that
// defines each referenced symbol.  This deliberately covers field and
// extension types, service method input/output types, extended messages
// and custom options (file-level, message, field, enum, service, method,
// oneof and extension-range options), because all of them make an import
// required.
class ReferenceCollector {
 public:
  explicit ReferenceCollector(const FileDescriptor& file) : file_(file) {}

  std::vector<SymbolReference> Collect() {
    RecordOptions(file_.options());
    for (int i = 0; i < file_.message_type_count(); ++i) {
      CollectMessage(*file_.message_type(i));
    }
    for (int i = 0; i < file_.enum_type_count(); ++i) {
      CollectEnum(*file_.enum_type(i));
    }
    for (int i = 0; i < file_.extension_count(); ++i) {
      CollectField(*file_.extension(i));
    }
    for (int i = 0; i < file_.service_count(); ++i) {
      CollectService(*file_.service(i));
    }
    return std::move(references_);
  }

 private:
  void AddReference(const std::string& name, const std::string& kind,
                    const FileDescriptor* defined_in) {
    if (defined_in == nullptr || defined_in == &file_) return;
    references_.push_back({name, kind, defined_in});
  }

  void AddReference(const Descriptor* descriptor) {
    if (descriptor == nullptr) return;
    AddReference(std::string(descriptor->full_name()), "message",
                 descriptor->file());
  }

  void AddReference(const EnumDescriptor* descriptor) {
    if (descriptor == nullptr) return;
    AddReference(std::string(descriptor->full_name()), "enum",
                 descriptor->file());
  }

  // Records custom options (option extensions) found on `options`, which
  // may be any of the concrete *Options messages.  Extension fields of the
  // options message are custom options defined in some imported file; the
  // import defining them must be counted as used even when nothing else
  // from that file is referenced.  Message-typed option values also keep
  // the file defining the option message type alive.
  //
  // Note that the DescriptorPool stores interpreted custom options in the
  // UnknownFieldSet of the generated options message, because the parser
  // compiled into this binary does not know extensions that are only
  // defined in the pool.  To make them visible, the options are
  // re-serialized and re-parsed with a dynamic message whose descriptor
  // comes from the file's own pool, which does know those extensions.
  void RecordOptions(const Message& options) {
    if (options.ByteSizeLong() == 0) return;
    const Descriptor* pool_type = file_.pool()->FindMessageTypeByName(
        std::string(options.GetDescriptor()->full_name()));
    if (pool_type == nullptr) {
      // The pool does not know the options type (no custom options can be
      // present in that case); fall back to the message as-is.
      RecordOptionsMessage(options);
      return;
    }
    DynamicMessageFactory factory;
    std::unique_ptr<Message> dynamic_options(
        factory.GetPrototype(pool_type)->New());
    if (!dynamic_options->ParseFromString(options.SerializeAsString())) {
      RecordOptionsMessage(options);
      return;
    }
    RecordOptionsMessage(*dynamic_options);
  }

  void RecordOptionsMessage(const Message& options) {
    std::vector<const FieldDescriptor*> fields;
    options.GetReflection()->ListFields(options, &fields);
    for (const FieldDescriptor* field : fields) {
      if (field->is_extension()) {
        AddReference(std::string(field->full_name()), "custom option",
                     field->file());
      }
      if (field->cpp_type() == FieldDescriptor::CPPTYPE_MESSAGE) {
        AddReference(field->message_type());
        if (field->is_repeated()) {
          int count = options.GetReflection()->FieldSize(options, field);
          for (int i = 0; i < count; ++i) {
            RecordOptionsMessage(
                options.GetReflection()->GetRepeatedMessage(options, field, i));
          }
        } else {
          RecordOptionsMessage(
              options.GetReflection()->GetMessage(options, field));
        }
      }
    }
  }

  void CollectField(const FieldDescriptor& field) {
    RecordOptions(field.options());
    if (field.is_extension()) {
      // The extended message must be visible to this file.
      AddReference(field.containing_type());
    }
    AddReference(field.message_type());
    AddReference(field.enum_type());
  }

  void CollectMessage(const Descriptor& message) {
    RecordOptions(message.options());
    for (int i = 0; i < message.field_count(); ++i) {
      CollectField(*message.field(i));
    }
    for (int i = 0; i < message.oneof_decl_count(); ++i) {
      RecordOptions(message.oneof_decl(i)->options());
    }
    for (int i = 0; i < message.extension_range_count(); ++i) {
      RecordOptions(message.extension_range(i)->options());
    }
    for (int i = 0; i < message.extension_count(); ++i) {
      CollectField(*message.extension(i));
    }
    for (int i = 0; i < message.nested_type_count(); ++i) {
      CollectMessage(*message.nested_type(i));
    }
    for (int i = 0; i < message.enum_type_count(); ++i) {
      CollectEnum(*message.enum_type(i));
    }
  }

  void CollectEnum(const EnumDescriptor& enum_descriptor) {
    RecordOptions(enum_descriptor.options());
    for (int i = 0; i < enum_descriptor.value_count(); ++i) {
      RecordOptions(enum_descriptor.value(i)->options());
    }
  }

  void CollectService(const ServiceDescriptor& service) {
    RecordOptions(service.options());
    for (int i = 0; i < service.method_count(); ++i) {
      const MethodDescriptor* method = service.method(i);
      RecordOptions(method->options());
      // Service method input/output types must be visible to this file.
      AddReference(method->input_type());
      AddReference(method->output_type());
    }
  }

  const FileDescriptor& file_;
  std::vector<SymbolReference> references_;
};

// Finds every chain of file names from `node` to `target` where the first
// edge is any import of the audited file and every later edge is a public
// import.  This mirrors exactly the visibility rules of the compiler.
void CollectChainsRecursive(const FileDescriptor* node,
                            const FileDescriptor* target, bool first_hop,
                            std::vector<std::string>* path,
                            std::set<std::string>* visited,
                            std::vector<std::vector<std::string>>* chains) {
  if (node == target) {
    chains->push_back(*path);
    return;
  }
  int count =
      first_hop ? node->dependency_count() : node->public_dependency_count();
  for (int i = 0; i < count; ++i) {
    const FileDescriptor* next =
        first_hop ? node->dependency(i) : node->public_dependency(i);
    if (next == nullptr ||
        visited->count(std::string(next->name())) != 0) {
      continue;
    }
    visited->insert(std::string(next->name()));
    path->push_back(std::string(next->name()));
    CollectChainsRecursive(next, target, /*first_hop=*/false, path, visited,
                           chains);
    path->pop_back();
    visited->erase(std::string(next->name()));
  }
}

// Orders chains so that the deterministic witness comes first: shortest
// chains win, ties are broken by file name.
bool ChainLess(const std::vector<std::string>& a,
               const std::vector<std::string>& b) {
  if (a.size() != b.size()) return a.size() < b.size();
  return a < b;
}

// Returns all visibility chains from `root` to `target`, sorted so that
// the first chain is the deterministic witness among possibly ambiguous
// equivalent chains.
std::vector<std::vector<std::string>> FindVisibilityChains(
    const FileDescriptor& root, const FileDescriptor& target) {
  std::vector<std::vector<std::string>> chains;
  std::vector<std::string> path{std::string(root.name())};
  std::set<std::string> visited{std::string(root.name())};
  CollectChainsRecursive(&root, &target, /*first_hop=*/true, &path, &visited,
                         &chains);
  std::sort(chains.begin(), chains.end(), ChainLess);
  chains.erase(std::unique(chains.begin(), chains.end()), chains.end());
  return chains;
}

bool IsPubliclyImportedBy(const FileDescriptor& importer,
                          const std::string& name) {
  for (int i = 0; i < importer.public_dependency_count(); ++i) {
    if (name == importer.public_dependency(i)->name()) return true;
  }
  return false;
}

bool ChainUsesPublicImport(const FileDescriptor& root,
                           const std::vector<std::string>& chain) {
  for (size_t i = 1; i < chain.size(); ++i) {
    const FileDescriptor* previous = root.pool()->FindFileByName(chain[i - 1]);
    if (previous != nullptr && IsPubliclyImportedBy(*previous, chain[i])) {
      return true;
    }
  }
  return false;
}

// Renders a chain like: a.proto -> b.proto -> (public) c.proto
std::string FormatChain(const FileDescriptor& root,
                        const std::vector<std::string>& chain) {
  std::string result = chain[0];
  for (size_t i = 1; i < chain.size(); ++i) {
    const FileDescriptor* previous = root.pool()->FindFileByName(chain[i - 1]);
    bool is_public =
        previous != nullptr && IsPubliclyImportedBy(*previous, chain[i]);
    absl::StrAppend(&result, is_public ? " -> (public) " : " -> ", chain[i]);
  }
  return result;
}

std::string FormatSymbol(const SymbolReference& reference) {
  return absl::StrCat(reference.name, " (", reference.kind, ")");
}

}  // namespace

ImportDiagnosticReport AnalyzeImportVisibility(const FileDescriptor& file) {
  ImportDiagnosticReport report;
  report.file = std::string(file.name());

  std::vector<SymbolReference> references = ReferenceCollector(file).Collect();

  // Group referenced symbols by the file defining them, keeping symbol
  // order deterministic and unique per (name, kind) pair.
  std::map<std::string, std::vector<SymbolReference>> used_by_file;
  {
    std::map<std::string, std::set<std::string>> seen;
    for (const SymbolReference& reference : references) {
      const std::string defining_file(reference.defined_in->name());
      if (seen[defining_file].insert(FormatSymbol(reference)).second) {
        used_by_file[defining_file].push_back(reference);
      }
    }
  }

  // Compute all visibility chains once per referenced file.
  std::map<std::string, std::vector<std::vector<std::string>>> chains_by_file;
  for (const auto& pair : used_by_file) {
    const FileDescriptor* target = file.pool()->FindFileByName(pair.first);
    if (target == nullptr) continue;
    chains_by_file[pair.first] = FindVisibilityChains(file, *target);
  }

  // One witness per referenced symbol.
  for (const auto& pair : used_by_file) {
    auto chains_it = chains_by_file.find(pair.first);
    for (const SymbolReference& reference : pair.second) {
      ImportVisibilityWitness witness;
      witness.symbol = reference.name;
      witness.defining_file = pair.first;
      if (chains_it != chains_by_file.end() && !chains_it->second.empty()) {
        witness.chain = chains_it->second.front();
        witness.via_public_import =
            ChainUsesPublicImport(file, witness.chain);
        witness.equivalent_chains.assign(chains_it->second.begin() + 1,
                                         chains_it->second.end());
      }
      report.witnesses.push_back(std::move(witness));
    }
  }
  std::sort(report.witnesses.begin(), report.witnesses.end(),
            [](const ImportVisibilityWitness& a,
               const ImportVisibilityWitness& b) {
              return a.symbol < b.symbol;
            });

  std::set<std::string> weak_imports;
  for (int i = 0; i < file.weak_dependency_count(); ++i) {
    weak_imports.insert(std::string(file.weak_dependency(i)->name()));
  }
  std::set<std::string> public_imports;
  for (int i = 0; i < file.public_dependency_count(); ++i) {
    public_imports.insert(std::string(file.public_dependency(i)->name()));
  }

  // Classify every import, in declaration order.
  for (int i = 0; i < file.dependency_count(); ++i) {
    const FileDescriptor* dependency = file.dependency(i);
    ImportDiagnosticEntry entry;
    entry.import = std::string(dependency->name());
    entry.is_weak = weak_imports.count(entry.import) != 0;
    entry.is_public = public_imports.count(entry.import) != 0;

    // Symbols defined directly in the imported file.
    auto direct_it = used_by_file.find(entry.import);
    if (direct_it != used_by_file.end()) {
      for (const SymbolReference& reference : direct_it->second) {
        entry.used_symbols.push_back(FormatSymbol(reference));
      }
    }

    // Symbols defined in files publicly re-exported by this import, and
    // whether every such symbol is also visible without this import.
    std::vector<std::vector<std::string>> transitive_chains;
    bool all_transitive_symbols_redundant = true;
    for (const auto& pair : used_by_file) {
      if (pair.first == entry.import) continue;
      auto chains_it = chains_by_file.find(pair.first);
      if (chains_it == chains_by_file.end() || chains_it->second.empty()) {
        continue;
      }
      bool visible_through_this_import = false;
      bool visible_elsewhere = false;
      const std::vector<std::string>* best_chain = nullptr;
      for (const auto& chain : chains_it->second) {
        if (chain.size() >= 2 && chain[1] == entry.import) {
          visible_through_this_import = true;
          if (best_chain == nullptr) best_chain = &chain;
        } else {
          visible_elsewhere = true;
        }
      }
      if (!visible_through_this_import) continue;
      if (!visible_elsewhere) all_transitive_symbols_redundant = false;
      transitive_chains.push_back(*best_chain);
      for (const SymbolReference& reference : pair.second) {
        entry.used_symbols.push_back(FormatSymbol(reference));
      }
    }

    std::sort(entry.used_symbols.begin(), entry.used_symbols.end());
    entry.used_symbols.erase(
        std::unique(entry.used_symbols.begin(), entry.used_symbols.end()),
        entry.used_symbols.end());
    std::sort(transitive_chains.begin(), transitive_chains.end(), ChainLess);

    if (entry.is_weak) {
      entry.usage = ImportUsageKind::kWeak;
      entry.removable = false;
      entry.reason =
          "weak import: retained for weak-linking semantics and never "
          "reported as unused";
    } else if (direct_it != used_by_file.end()) {
      entry.usage = ImportUsageKind::kUsedDirect;
      entry.removable = false;
      entry.reason = absl::StrCat(
          "required: ", direct_it->second.size(), " symbol(s) from \"",
          entry.import, "\" are referenced: ",
          absl::StrJoin(entry.used_symbols, ", "));
      if (!transitive_chains.empty()) {
        absl::StrAppend(&entry.reason,
                        "; also re-exports symbols used by this file, e.g. "
                        "witness chain: ",
                        FormatChain(file, transitive_chains.front()));
      }
    } else if (!transitive_chains.empty()) {
      entry.usage = ImportUsageKind::kUsedPublicTransitive;
      entry.removable = all_transitive_symbols_redundant;
      entry.reason = absl::StrCat(
          "no symbol from \"", entry.import,
          "\" itself is referenced, but symbols from its public re-exports "
          "are used: ",
          absl::StrJoin(entry.used_symbols, ", "), "; witness chain: ",
          FormatChain(file, transitive_chains.front()));
      absl::StrAppend(&entry.reason,
                      entry.removable
                          ? "; every such symbol is also visible through "
                            "another import chain, so this import is redundant"
                          : "; this import is the only chain making some of "
                            "these symbols visible");
    } else if (entry.is_public) {
      entry.usage = ImportUsageKind::kPublicReexport;
      entry.removable = false;
      entry.reason = absl::StrCat(
          "not referenced by this file, but re-exported with 'import "
          "public'; removing it may break files that import \"",
          file.name(), "\"");
    } else {
      entry.usage = ImportUsageKind::kUnused;
      entry.removable = true;
      entry.reason = absl::StrCat(
          "no type, extension, service method, or custom option from \"",
          entry.import, "\" or its public re-exports is referenced by \"",
          file.name(), "\"; safe to remove");
    }
    report.imports.push_back(std::move(entry));
  }

  return report;
}

std::string FormatImportDiagnosticReport(const ImportDiagnosticReport& report) {
  std::string out;
  absl::StrAppend(&out, "import diagnostic for \"", report.file, "\":\n");
  absl::StrAppend(&out, "  imports:\n");
  if (report.imports.empty()) {
    absl::StrAppend(&out, "    (no imports)\n");
  }
  for (const ImportDiagnosticEntry& entry : report.imports) {
    absl::string_view usage_label = "unused";
    switch (entry.usage) {
      case ImportUsageKind::kUsedDirect:
        usage_label = "used (direct)";
        break;
      case ImportUsageKind::kUsedPublicTransitive:
        usage_label = "used (public-transitive)";
        break;
      case ImportUsageKind::kUnused:
        usage_label = "unused";
        break;
      case ImportUsageKind::kWeak:
        usage_label = "weak";
        break;
      case ImportUsageKind::kPublicReexport:
        usage_label = "public re-export";
        break;
    }
    absl::StrAppend(&out, "    \"", entry.import, "\": ", usage_label);
    if (entry.removable) absl::StrAppend(&out, " [removable]");
    if (entry.is_weak) absl::StrAppend(&out, " [weak]");
    absl::StrAppend(&out, "\n");
    for (const std::string& symbol : entry.used_symbols) {
      absl::StrAppend(&out, "      symbol: ", symbol, "\n");
    }
    absl::StrAppend(&out, "      reason: ", entry.reason, "\n");
  }
  absl::StrAppend(&out, "  visibility witnesses:\n");
  if (report.witnesses.empty()) {
    absl::StrAppend(&out, "    (no external references)\n");
  }
  for (const ImportVisibilityWitness& witness : report.witnesses) {
    absl::StrAppend(&out, "    ", witness.symbol, " (defined in ",
                    witness.defining_file, "): ");
    if (witness.chain.empty()) {
      absl::StrAppend(&out, "(no import chain)\n");
      continue;
    }
    absl::StrAppend(&out, absl::StrJoin(witness.chain, " -> "));
    if (witness.via_public_import) {
      absl::StrAppend(&out, " [public import chain]");
    }
    absl::StrAppend(&out, "\n");
    if (!witness.equivalent_chains.empty()) {
      absl::StrAppend(&out, "      ambiguous: ",
                      witness.equivalent_chains.size(),
                      " equivalent chain(s); witness chosen deterministically "
                      "by file name:");
      size_t shown = 0;
      for (const auto& chain : witness.equivalent_chains) {
        if (shown++ == 3) {
          absl::StrAppend(&out, " ...");
          break;
        }
        absl::StrAppend(&out, " ", absl::StrJoin(chain, " -> "), ";");
      }
      absl::StrAppend(&out, "\n");
    }
  }
  return out;
}

}  // namespace compiler
}  // namespace protobuf
}  // namespace google
