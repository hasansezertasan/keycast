# keycast Documentation

Welcome to the keycast documentation! This directory contains comprehensive documentation for the keycast project, covering architecture, API, design decisions, and project overview.

## Documentation Structure

### 📋 [Project Overview](PROJECT_OVERVIEW.md)
Complete project overview including:
- Project summary and key features
- Target use cases and technical architecture
- Technology stack and project structure
- Development workflow and quality assurance
- Configuration system and performance characteristics
- Security, privacy, and testing strategy
- Deployment, roadmap, and community information

### 🏗️ [Architecture Documentation](ARCHITECTURE.md)
Detailed technical architecture including:
- System architecture and component design
- Data flow and communication patterns
- Threading model and performance considerations
- Error handling and security considerations
- Platform compatibility and future considerations
- Dependencies and build system

### 🔧 [API Documentation](API.md)
Complete API reference including:
- All public classes and methods
- Detailed parameter descriptions and examples
- Usage patterns and best practices
- Error handling and threading considerations
- Platform-specific notes and performance tips
- Debugging and testing guidance

### 🎯 [Design Decisions](DESIGN_DECISIONS.md)
Comprehensive design rationale including:
- Technology stack decisions and alternatives
- Architecture and user experience decisions
- Performance and security considerations
- Testing and configuration strategies
- Error handling and future considerations
- Trade-offs and rationale for each decision

### ⚖️ [Comparison / Alternatives](COMPARISON.md)
How keycast compares to other keystroke/mouse visualizers:
- Feature matrix vs KeyCastr, Keyviz, and VS Code Screencast Mode
- Why keycast can't show semantic command names system-wide
- Honest "when to choose what" guidance

## Quick Start

### For Users
1. Read the [Project Overview](PROJECT_OVERVIEW.md) to understand what keycast does
2. Check the main [README.md](../README.md) for installation and usage instructions
3. Refer to [API Documentation](API.md) for advanced configuration and customization

### For Developers
1. Start with [Project Overview](PROJECT_OVERVIEW.md) for project understanding
2. Read [Architecture Documentation](ARCHITECTURE.md) for technical details
3. Review [Design Decisions](DESIGN_DECISIONS.md) to understand the rationale
4. Use [API Documentation](API.md) for implementation details

### For Contributors
1. Read [Project Overview](PROJECT_OVERVIEW.md) for contribution guidelines
2. Study [Architecture Documentation](ARCHITECTURE.md) for code structure
3. Review [Design Decisions](DESIGN_DECISIONS.md) for design principles
4. Use [API Documentation](API.md) for implementation reference

## Documentation Philosophy

### Comprehensive Coverage
- **Complete API Reference**: Every public method and class documented
- **Architectural Details**: Deep dive into system design and decisions
- **Design Rationale**: Why decisions were made, not just what was decided
- **Practical Examples**: Real-world usage examples and patterns

### User-Focused
- **Multiple Audiences**: Content for users, developers, and contributors
- **Progressive Disclosure**: Start simple, provide depth when needed
- **Cross-References**: Links between related concepts and sections
- **Practical Guidance**: Real-world examples and best practices

### Maintainable
- **Living Documentation**: Updated with code changes
- **Version Controlled**: Documentation changes tracked in git
- **Structured Format**: Consistent organization and formatting
- **Quality Standards**: Clear, accurate, and comprehensive content

## Key Concepts

### Core Components
- **Keycast** (`application.py`): Orchestrates all components and owns the lifecycle
- **DisplayWindow**: The visual overlay that shows events (implements the `TextSink` protocol)
- **KeyListener**: Captures and processes keyboard input
- **MouseListener**: Captures and processes mouse input
- **Settings**: Manages configuration with Pydantic validation
- **Logging Setup**: Configures logging system
- **Entry points** (`main.py`, `cli.py`, `__main__.py`): Thin wrappers that run `Keycast`

### Design Principles
- **Modularity**: Clean separation of concerns
- **Cross-platform**: Works on macOS, Linux, and Windows
- **Privacy-first**: Local processing, no data transmission
- **User Control**: Configurable behavior and appearance
- **Performance**: Efficient resource usage and responsiveness

### Technology Choices
- **Python 3.14+**: Modern Python with type hints
- **pynput**: Cross-platform input monitoring
- **Pydantic**: Settings validation and configuration management
- **Tkinter**: Built-in GUI framework
- **uv**: Modern package management

## Getting Help

### Documentation Issues
- **Missing Information**: Check if the information exists in another document
- **Outdated Content**: Report outdated information via GitHub issues
- **Clarity Issues**: Suggest improvements for unclear sections
- **Examples**: Request additional examples for complex topics

### Development Questions
- **Architecture**: Refer to [Architecture Documentation](ARCHITECTURE.md)
- **API Usage**: Check [API Documentation](API.md)
- **Design Decisions**: Review [Design Decisions](DESIGN_DECISIONS.md)
- **Implementation**: Look at the source code and tests

### Community Support
- **GitHub Issues**: Report bugs and request features
- **Discussions**: Ask questions and share ideas
- **Pull Requests**: Contribute improvements and fixes
- **Documentation**: Help improve the documentation

## Contributing to Documentation

### Types of Contributions
- **Content Updates**: Fix outdated information
- **New Sections**: Add missing documentation
- **Examples**: Provide more practical examples
- **Clarity**: Improve unclear explanations
- **Structure**: Suggest better organization

### Documentation Standards
- **Accuracy**: Ensure all information is correct and up-to-date
- **Clarity**: Write clear, concise, and understandable content
- **Completeness**: Provide comprehensive coverage of topics
- **Consistency**: Follow established patterns and formatting
- **Examples**: Include practical examples where helpful

### Review Process
- **Self-Review**: Check your changes before submitting
- **Peer Review**: Have others review your documentation changes
- **Testing**: Verify that examples and instructions work
- **Integration**: Ensure changes fit with existing documentation

## Version Information

### Documentation Version
- **Current Version**: 1.1.0
- **Last Updated**: 2024
- **Compatible With**: keycast 0.1.0+

### Update History
- **v1.1.0**: Updated for Pydantic settings system
  - Updated API documentation for new Settings classes
  - Updated architecture documentation for settings system
  - Updated design decisions for Pydantic integration
  - Updated project overview for current dependencies
- **v1.0.0**: Initial comprehensive documentation
  - Complete API documentation
  - Architecture and design decisions
  - Project overview and guidelines

## Related Resources

### External Documentation
- **Python Documentation**: [python.org/docs](https://docs.python.org/)
- **pynput Documentation**: [pynput.readthedocs.io](https://pynput.readthedocs.io/)
- **Pydantic Documentation**: [docs.pydantic.dev](https://docs.pydantic.dev/)
- **Tkinter Documentation**: [tkinter documentation](https://docs.python.org/3/library/tkinter.html)
- **uv Documentation**: [docs.astral.sh/uv](https://docs.astral.sh/uv/)

### Project Resources
- **Main README**: [../README.md](../README.md)
- **Source Code**: [../src/keycast/](../src/keycast/)
- **Tests**: [../tests/](../tests/)
- **Configuration**: [../pyproject.toml](../pyproject.toml)

### Community Resources
- **GitHub Repository**: Project repository
- **Issue Tracker**: Bug reports and feature requests
- **Discussions**: Community discussions and Q&A
- **Contributing Guide**: How to contribute to the project

---

*This documentation is maintained as part of the keycast project. For questions, suggestions, or contributions, please visit the project repository.*
