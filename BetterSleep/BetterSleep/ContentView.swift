import SwiftUI

struct ContentView: View {
    // This is the main source of truth for authentication in the app
    @StateObject private var authVM = AuthViewModel()
    
    var body: some View {
        Group {
            if authVM.isAuthenticated {
                // MARK: - Main App Navigation
                TabView {
                    // 1. The new Dashboard Tab
                    DashboardView()
                        .tabItem {
                            Label("Dashboard", systemImage: "chart.xyaxis.line")
                        }
                    
                    // 2. The existing Homes/Rooms Tab
                    HousesListView()
                        .tabItem {
                            Label("My Homes", systemImage: "house.fill")
                        }
                }
                // We inject the AuthViewModel so any tab can sign the user out (like your ProfileView!)
                .environmentObject(authVM)
                
            } else {
                // Pass the authVM into the LoginView so it can trigger sign-ins
                LoginView(authVM: authVM)
            }
        }
        .task {
            // Check for an existing session when the app launches
            await authVM.checkSession()
        }
    }
}

#Preview {
    ContentView()
}
