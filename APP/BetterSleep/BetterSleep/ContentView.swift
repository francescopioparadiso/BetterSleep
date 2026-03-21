import SwiftUI

struct ContentView: View {
    // This is the main source of truth for authentication in the app
    @StateObject private var authVM = AuthModel()
    
    var body: some View {
        Group {
            if authVM.isAuthenticated {
                // MARK: - Standard Tab Navigation
                TabView {
                    Tab("Dashboard", systemImage: "chart.bar.fill") {
                        ChartsView()
                    }

                    Tab("My Homes", systemImage: "house.fill") {
                        HouseView()
                    }

                    Tab("Profile", systemImage: "person.fill", role: .search) {
                        ProfileView()
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
