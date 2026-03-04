import SwiftUI

struct ContentView: View {
    // This is the main source of truth for authentication in the app
    @StateObject private var authVM = AuthModel()
    
    var body: some View {
        Group {
            if authVM.isAuthenticated {
                // MARK: - Standard Tab Navigation
                TabView {
                    // 1. The Dashboard Tab
                    ChartsView()
                        .tabItem {
                            Label("Dashboard", systemImage: "chart.bar.fill")
                        }
                    
                    // 2. The HouseView Tab
                    HouseView()
                        .tabItem {
                            Label("My Homes", systemImage: "house.fill")
                        }
                }
                .environmentObject(authVM)
                
            } else {
                AuthView(authVM: authVM)
            }
        }
        .onAppear {
            authVM.checkSession()
        }
    }
}

#Preview {
    ContentView()
}
