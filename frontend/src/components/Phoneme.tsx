/** An IPA symbol (or sequence), set in Charis SIL so every glyph renders. */
export default function Phoneme({ ipa, slashes = true }: { ipa: string; slashes?: boolean }) {
  return <span className="ipa">{slashes ? `/${ipa}/` : ipa}</span>;
}
