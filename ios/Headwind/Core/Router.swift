import Observation

/// Screens that can be pushed onto a tab's NavigationStack.
enum Route: Hashable {
    case recordings
    case sensors
}

/// A tab's navigation path, injected with @Environment so any view in the tab can push a Route.
@MainActor
@Observable
final class Router {
    var path: [Route] = []

    func show(_ route: Route) {
        path.append(route)
    }
}
