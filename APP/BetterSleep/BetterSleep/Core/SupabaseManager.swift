import Foundation
import Supabase

let supabaseURL = URL(string: "https://jcctrjafuhftbrnqfxlw.supabase.co")!
let supabaseKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpjY3RyamFmdWhmdGJybnFmeGx3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE5MzA3MDgsImV4cCI6MjA4NzUwNjcwOH0.CdFOmqoxsg1FT0HenNSO-YDMs1HRHgixuf4rfdx704U"

let supabase = SupabaseClient(
    supabaseURL: supabaseURL,
    supabaseKey: supabaseKey,
    options: SupabaseClientOptions(
        auth: SupabaseClientOptions.AuthOptions(
            emitLocalSessionAsInitialSession: true
        )
    )
)
