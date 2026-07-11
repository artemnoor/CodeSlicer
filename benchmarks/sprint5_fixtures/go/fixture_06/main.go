package orders6

import "github.com/gin-gonic/gin"

type Store6 struct{}
func (s *Store6) Save() {}
type Service6 struct{ store *Store6 }
func (s *Service6) Create() { s.store.Save() }
type Handler6 struct{ service *Service6 }
func (h *Handler6) Handle() { h.service.Create() }
func Routes6(r *gin.Engine, h *Handler6) { r.GET("/orders/6", h.Handle) }
