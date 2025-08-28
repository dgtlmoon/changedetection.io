Directory of docs

## Regenerating API Documentation

### Modern Interactive API Docs (Recommended)

To regenerate the modern API documentation, run from the `docs/` directory:

```bash
# Install dependencies (first time only)
npm install

# Generate the HTML documentation from OpenAPI spec using Redoc
npm run build-docs
```

### OpenAPI Specification

The OpenAPI specification (`docs/api-spec.yaml`) is the source of truth for API documentation. This industry-standard format enables:

- **Interactive documentation** - Test endpoints directly in the browser
- **SDK generation** - Auto-generate client libraries for any programming language  
- **API validation** - Ensure code matches documentation
- **Integration tools** - Import into Postman, Insomnia, API gateways, etc.

**Important:** When adding or modifying API endpoints, you must update `docs/api-spec.yaml` to keep documentation in sync:

1. Edit `docs/api-spec.yaml` with new endpoints, parameters, or response schemas
2. Run `npm run build-docs` to regenerate the HTML documentation
3. Commit both the YAML spec and generated HTML files



