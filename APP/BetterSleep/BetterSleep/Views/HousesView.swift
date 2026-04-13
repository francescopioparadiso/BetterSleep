import SwiftUI
import UIKit

private func flagForHouse(_ name: String) -> String {
    let n = name.lowercased()
    // Italian cities
    if n.contains("roma") || n.contains("rome") || n.contains("milano") || n.contains("milan")
        || n.contains("torino") || n.contains("turin") || n.contains("napol") || n.contains("firenz")
        || n.contains("florence") || n.contains("venezia") || n.contains("venice") || n.contains("bologna")
        || n.contains("italia") || n.contains("italy") || n.contains("genova") || n.contains("palermo")
        || n.contains("bari") || n.contains("catania") { return "🇮🇹" }
    // UK
    if n.contains("london") || n.contains("manchester") || n.contains("liverpool") || n.contains("birmingham")
        || n.contains("uk") || n.contains("england") || n.contains("edinburgh") || n.contains("scotland") { return "🇬🇧" }
    // USA
    if n.contains("new york") || n.contains("los angeles") || n.contains("chicago") || n.contains("miami")
        || n.contains("san francisco") || n.contains("boston") || n.contains("seattle")
        || n.contains("usa") || n.contains("america") { return "🇺🇸" }
    // France
    if n.contains("paris") || n.contains("lyon") || n.contains("marseille") || n.contains("france")
        || n.contains("nice") || n.contains("toulouse") { return "🇫🇷" }
    // Germany
    if n.contains("berlin") || n.contains("munich") || n.contains("münchen") || n.contains("hamburg")
        || n.contains("frankfurt") || n.contains("german") { return "🇩🇪" }
    // Spain
    if n.contains("madrid") || n.contains("barcelona") || n.contains("spain") || n.contains("sevilla")
        || n.contains("valencia") { return "🇪🇸" }
    // Japan
    if n.contains("tokyo") || n.contains("osaka") || n.contains("japan") || n.contains("kyoto") { return "🇯🇵" }
    // Default house emoji
    return "🏠"
}

private final class EmojiPaletteCache {
    static let shared = EmojiPaletteCache()
    private var cache: [String: [UIColor]] = [:]

    func colors(for emoji: String) -> [UIColor] {
        if let cached = cache[emoji] {
            return cached
        }
        let extracted = extractDominantColors(from: emoji)
        let result = extracted.isEmpty ? [UIColor.systemIndigo, UIColor.systemBlue] : extracted
        cache[emoji] = result
        return result
    }
}

private func extractDominantColors(from emoji: String) -> [UIColor] {
    let size = CGSize(width: 64, height: 64)
    let renderer = UIGraphicsImageRenderer(size: size)
    let image = renderer.image { context in
        UIColor.clear.setFill()
        context.fill(CGRect(origin: .zero, size: size))
        let attrs: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: 56)
        ]
        let textSize = emoji.size(withAttributes: attrs)
        let textRect = CGRect(
            x: (size.width - textSize.width) / 2,
            y: (size.height - textSize.height) / 2,
            width: textSize.width,
            height: textSize.height
        )
        emoji.draw(in: textRect, withAttributes: attrs)
    }

    guard let cgImage = image.cgImage,
          let data = cgImage.dataProvider?.data,
          let ptr = CFDataGetBytePtr(data) else {
        return []
    }

    let width = cgImage.width
    let height = cgImage.height
    let bytesPerPixel = 4
    let bytesPerRow = cgImage.bytesPerRow

    var buckets: [Int: (count: Int, r: Int, g: Int, b: Int)] = [:]

    for y in 0..<height {
        for x in 0..<width {
            let i = y * bytesPerRow + x * bytesPerPixel
            let r = Int(ptr[i])
            let g = Int(ptr[i + 1])
            let b = Int(ptr[i + 2])
            let a = Int(ptr[i + 3])

            if a < 30 { continue }

            var hue: CGFloat = 0
            var saturation: CGFloat = 0
            var brightness: CGFloat = 0
            UIColor(
                red: CGFloat(r) / 255.0,
                green: CGFloat(g) / 255.0,
                blue: CGFloat(b) / 255.0,
                alpha: 1.0
            ).getHue(&hue, saturation: &saturation, brightness: &brightness, alpha: nil)

            if saturation < 0.18 || brightness < 0.12 { continue }

            let qr = r / 32
            let qg = g / 32
            let qb = b / 32
            let key = (qr << 16) | (qg << 8) | qb

            let existing = buckets[key] ?? (0, 0, 0, 0)
            buckets[key] = (
                count: existing.count + 1,
                r: existing.r + r,
                g: existing.g + g,
                b: existing.b + b
            )
        }
    }

    let sorted = buckets.values.sorted { $0.count > $1.count }
    var picked: [UIColor] = []

    for entry in sorted {
        if picked.count == 2 { break }
        let c = UIColor(
            red: CGFloat(entry.r) / CGFloat(entry.count) / 255.0,
            green: CGFloat(entry.g) / CGFloat(entry.count) / 255.0,
            blue: CGFloat(entry.b) / CGFloat(entry.count) / 255.0,
            alpha: 1.0
        )
        if picked.isEmpty {
            picked.append(c)
        } else if isColorDistinct(c, from: picked[0]) {
            picked.append(c)
        }
    }

    if picked.count == 1 {
        picked.append(picked[0])
    }
    return picked
}

private func isColorDistinct(_ a: UIColor, from b: UIColor) -> Bool {
    var ar: CGFloat = 0, ag: CGFloat = 0, ab: CGFloat = 0, aa: CGFloat = 0
    var br: CGFloat = 0, bg: CGFloat = 0, bb: CGFloat = 0, ba: CGFloat = 0
    a.getRed(&ar, green: &ag, blue: &ab, alpha: &aa)
    b.getRed(&br, green: &bg, blue: &bb, alpha: &ba)
    let dr = ar - br
    let dg = ag - bg
    let db = ab - bb
    let distance = sqrt(dr * dr + dg * dg + db * db)
    return distance > 0.22
}

private func iconGlowColors(for emoji: String) -> (Color, Color) {
    let palette = EmojiPaletteCache.shared.colors(for: emoji)
    if palette.count >= 2 {
        return (Color(palette[0]), Color(palette[1]))
    }
    let first = palette.first.map(Color.init) ?? .indigo
    return (first, first)
}

struct HouseView: View {
    @StateObject private var viewModel: HouseModel
    @StateObject private var roomModel = RoomModel()
    private let shouldAutoLoad: Bool
    
    @State private var newHouseName = ""
    @State private var activeRoomsByHouse: [Int: Bool] = [:]
    
    private var currentUserId: Int? {
        if let idString = UserDefaults.standard.string(forKey: "currentUserId"), let id = Int(idString) {
            return id
        }
        return nil
    }

    private var sortedPendingInvites: [Invitation] {
        viewModel.pendingInvites.sorted {
            let lhs = viewModel.pendingInviteHouseNames[$0.house_id] ?? "House \($0.house_id)"
            let rhs = viewModel.pendingInviteHouseNames[$1.house_id] ?? "House \($1.house_id)"
            return lhs.localizedCaseInsensitiveCompare(rhs) == .orderedAscending
        }
    }

    @MainActor
    init(shouldAutoLoad: Bool = true) {
        _viewModel = StateObject(wrappedValue: HouseModel())
        self.shouldAutoLoad = shouldAutoLoad
    }

    init(viewModel: HouseModel, shouldAutoLoad: Bool = true) {
        _viewModel = StateObject(wrappedValue: viewModel)
        self.shouldAutoLoad = shouldAutoLoad
    }
    
    var body: some View {
        NavigationView {
            Group {
                if viewModel.isLoading {
                    ProgressView("Loading your homes...")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    List {
                        ForEach(viewModel.houses) { house in
                            NavigationLink(destination: RoomsView(house: house)) {
                                HStack(spacing: 14) {
                                    if activeRoomsByHouse[house.id ?? 0] == true {
                                        Image(systemName: "star.fill")
                                            .font(.title)
                                            .foregroundColor(.yellow)
                                            .padding(6)
                                            .shadow(color: .yellow, radius: 10, x: 0, y: 0)
                                            .frame(width: 40)
                                            .contentTransition(.symbolEffect(.replace.magic(fallback: .downUp.byLayer)))
                                    } else {
                                        let emoji = flagForHouse(house.name)
                                        let glow = iconGlowColors(for: emoji)
                                        Text(emoji)
                                            .font(.title)
                                            .shadow(color: glow.0.opacity(0.45), radius: 7, x: 0, y: 0)
                                            .shadow(color: glow.1.opacity(0.28), radius: 13, x: 0, y: 0)
                                            .frame(width: 40)
                                            .contentTransition(.symbolEffect(.replace.magic(fallback: .downUp.byLayer)))
                                        }
                                    
                                    Text(house.name)
                                        .font(.headline)
                                        .fontWeight(.semibold)
                                        .fontDesign(.rounded)
                                }
                            }
                            .padding(.vertical, 6)
                        }
                        .onDelete { indexSet in
                            Task { await viewModel.deleteHouse(at: indexSet) }
                        }

                        // Pending invitations appear after houses and add-row, sorted alphabetically by house name.
                        ForEach(sortedPendingInvites) { invite in
                            let houseName = viewModel.pendingInviteHouseNames[invite.house_id] ?? "House \(invite.house_id)"
                            let emoji = flagForHouse(houseName)
                            let glow = iconGlowColors(for: emoji)

                            HStack(spacing: 10) {
                                Text(emoji)
                                    .font(.title2)
                                    .shadow(color: glow.0.opacity(0.45), radius: 6, x: 0, y: 0)
                                    .shadow(color: glow.1.opacity(0.28), radius: 10, x: 0, y: 0)
                                    .frame(width: 32)
                                    .contentTransition(.symbolEffect(.replace.magic(fallback: .downUp.byLayer)))

                                VStack(alignment: .leading, spacing: 2) {
                                    Text(houseName)
                                        .font(.headline)
                                        .fontWeight(.semibold)
                                        .fontDesign(.rounded)
                                    Text("Invited by \(invite.email)")
                                        .font(.caption)
                                        .fontDesign(.rounded)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                        .truncationMode(.tail)
                                }

                                Spacer()

                                HStack(spacing: 6) {
                                    Button(action: {
                                        Task { await viewModel.acceptInvite(invite: invite) }
                                    }) {
                                        Text("Accept")
                                            .fontDesign(.rounded)
                                            .fixedSize()
                                    }
                                    .buttonStyle(.glassProminent)
                                    .foregroundStyle(Color.green)
                                    .tint(Color.green.opacity(0.15))

                                    Button(action: {
                                        Task { await viewModel.rejectInvite(invite: invite) }
                                    }) {
                                        Text("Decline")
                                            .fontDesign(.rounded)
                                            .fixedSize()
                                    }
                                    .buttonStyle(.glassProminent)
                                    .foregroundStyle(Color.red)
                                    .tint(Color.red.opacity(0.15))
                                }
                            }
                            .padding(.vertical, 4)
                        }
                        
                        addHouseRow
                    }
                    .listStyle(.insetGrouped)
                    .refreshable {
                        await refreshData()
                    }
                }
            }
            .navigationTitle("Houses")
            .task {
                if shouldAutoLoad {
                    await refreshData()
                }
            }
            .onAppear {
                Task {
                    if let userId = currentUserId {
                        await fetchActiveRooms(for: userId)
                    }
                }
            }
        }
    }

    private var addHouseRow: some View {
        let previewEmoji = flagForHouse(newHouseName.isEmpty ? "home" : newHouseName)
        let glow = iconGlowColors(for: previewEmoji)

        return HStack(spacing: 14) {
            Text(previewEmoji)
                .font(.title)
                .shadow(color: glow.0.opacity(0.45), radius: 7, x: 0, y: 0)
                .shadow(color: glow.1.opacity(0.28), radius: 13, x: 0, y: 0)
                .frame(width: 40)
                .contentTransition(.numericText(value: Double(previewEmoji.hashValue)))
                .animation(.snappy, value: previewEmoji)

            TextField("Type your new home name", text: $newHouseName)
                .font(.headline)
                .fontWeight(.semibold)
                .fontDesign(.rounded)
                .textInputAutocapitalization(.words)
                .autocorrectionDisabled(true)
                .submitLabel(.done)
                .onSubmit {
                    Task { await createHouseFromInput() }
                }
        }
        .padding(.vertical, 6)
    }

    private func createHouseFromInput() async {
        let trimmed = newHouseName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        await viewModel.addHouse(name: trimmed)
        newHouseName = ""
    }

    private func refreshData() async {
        await viewModel.fetchHouses()
        await viewModel.fetchPendingInvites()
        if let userId = currentUserId {
            await fetchActiveRooms(for: userId)
        }
    }
    
    private func fetchActiveRooms(for userId: Int) async {
        do {
            let base = try await CatalogClient.shared.getUserServiceURL()
            let url = URL(string: "\(base)/getActiveRoom?user_id=\(userId)")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            
            // Reset active rooms first
            await MainActor.run {
                activeRoomsByHouse.removeAll()
            }
            
            if let activeRoomData = json?["active_room"] as? [String: Any],
               let houseId = activeRoomData["house_id"] as? Int {
                await MainActor.run {
                    activeRoomsByHouse[houseId] = true
                }
            }
        } catch {
            print("Error fetching active room: \(error)")
        }
    }
}

private func makePreviewHouseVM(withHouses: Bool) -> HouseModel {
    let vm = HouseModel()
    vm.isLoading = false
    vm.pendingInvites = []
    vm.houses = withHouses
        ? [
            House(id: 1, name: "Torino Home", created_at: nil),
            House(id: 2, name: "Milan Loft", created_at: nil)
          ]
        : []
    return vm
}

#Preview("With Houses") {
    HouseView(viewModel: makePreviewHouseVM(withHouses: true), shouldAutoLoad: false)
}

#Preview("Without Houses") {
    HouseView(viewModel: makePreviewHouseVM(withHouses: false), shouldAutoLoad: false)
}
